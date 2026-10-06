"""Persistencia del Chat (monitor de TEXT_MESSAGE_APP).

`SqlChatRepository.add` se llama desde el mismo `_on_message` que ya narra
Actividad 2.0 (`application/ingest.py`), dentro de la misma transacción de
ingesta — un paquete de texto genera su fila de `chat_messages` igual que
genera su `ActivityEvent`, sin una segunda pasada ni una cola aparte.
"""

from dataclasses import fields
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import ChatMessageModel
from noc.domain.chat.entities import ChatMessage

_ENTITY_FIELDS = [f.name for f in fields(ChatMessage) if f.name != "id"]


def _like_pattern(s: str) -> str:
    """Escapa un literal para usarlo dentro de LIKE ... ESCAPE '\\\\'."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_entity(m: ChatMessageModel) -> ChatMessage:
    return ChatMessage(**{f: getattr(m, f) for f in _ENTITY_FIELDS}, id=m.id)


class SqlChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, msg: ChatMessage) -> ChatMessage:
        m = ChatMessageModel(**{f: getattr(msg, f) for f in _ENTITY_FIELDS})
        self._session.add(m)
        await self._session.flush()
        return _to_entity(m)

    async def list_messages(
        self,
        limit: int,
        before_id: int | None = None,
        channel_index: int | None = None,
        dm_only: bool = False,
        broadcast_only: bool = False,
        node_id: str | None = None,
        gateway_id: str | None = None,
        q: str | None = None,
        since: Any | None = None,
    ) -> list[ChatMessage]:
        """Más recientes primero (mismo orden que el Registro), antes de
        antes de `before_id` — scroll infinito hacia atrás.

        `since` (datetime): usado por el escaneo Nexus (ADR 0027) para acotar
        a los mensajes recibidos durante la ventana de escucha, sin depender
        de `channel_index` (el backend no sabe qué índice auto-detectó el
        gateway para el canal Nexus/JenT)."""
        stmt = select(ChatMessageModel).order_by(ChatMessageModel.id.desc()).limit(limit)
        if before_id is not None:
            stmt = stmt.where(ChatMessageModel.id < before_id)
        if channel_index is not None:
            stmt = stmt.where(ChatMessageModel.channel_index == channel_index)
        if since is not None:
            stmt = stmt.where(ChatMessageModel.received_at >= since)
        if dm_only:
            stmt = stmt.where(ChatMessageModel.to_node_id.is_not(None))
        elif broadcast_only:
            stmt = stmt.where(ChatMessageModel.to_node_id.is_(None))
        if node_id:
            stmt = stmt.where(
                or_(ChatMessageModel.from_node_id == node_id, ChatMessageModel.to_node_id == node_id)
            )
        if gateway_id:
            stmt = stmt.where(ChatMessageModel.gateway_id == gateway_id)
        if q:
            pattern = f"%{_like_pattern(q.lower())}%"
            stmt = stmt.where(func.lower(ChatMessageModel.text).like(pattern, escape="\\"))
        rows = await self._session.scalars(stmt)
        return [_to_entity(r) for r in rows]

    async def list_for_channels(
        self, pairs: list[tuple[str, int]], limit: int, before_id: int | None = None
    ) -> list[ChatMessage]:
        """Difusiones de los pares (gateway_id, channel_index) dados — base
        de la consola Nexus (el canal Nexus lo conoce cada pasarela por
        nombre). Más recientes primero."""
        if not pairs:
            return []
        stmt = (
            select(ChatMessageModel)
            .where(
                ChatMessageModel.to_node_id.is_(None),
                or_(
                    *[
                        (ChatMessageModel.gateway_id == gw) & (ChatMessageModel.channel_index == idx)
                        for gw, idx in pairs
                    ]
                ),
            )
            .order_by(ChatMessageModel.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(ChatMessageModel.id < before_id)
        rows = await self._session.scalars(stmt)
        return [_to_entity(r) for r in rows]

    async def list_channels(self) -> list[dict[str, Any]]:
        """Canales conocidos (broadcast) por los que ha circulado tráfico:
        base del selector "Todos / Canal 0 / Canal 1 / ...". Los DM no son
        un canal — se cuentan aparte con `dm_count`."""
        stmt = (
            select(
                ChatMessageModel.channel_index,
                ChatMessageModel.channel_name,
                func.count().label("message_count"),
                func.max(ChatMessageModel.received_at).label("last_message_at"),
            )
            .where(ChatMessageModel.to_node_id.is_(None))
            .group_by(ChatMessageModel.channel_index, ChatMessageModel.channel_name)
            .order_by(ChatMessageModel.channel_index)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "channel_index": r.channel_index,
                "channel_name": r.channel_name,
                "message_count": r.message_count,
                "last_message_at": r.last_message_at,
            }
            for r in rows
        ]

    async def list_channels_by_gateway(self) -> list[dict[str, Any]]:
        """Igual que `list_channels` pero separado por pasarela: cada gateway
        tiene su propia malla/canales, la UI pinta una fila por pasarela."""
        stmt = (
            select(
                ChatMessageModel.gateway_id,
                ChatMessageModel.channel_index,
                ChatMessageModel.channel_name,
                func.count().label("message_count"),
                func.max(ChatMessageModel.received_at).label("last_message_at"),
            )
            .where(ChatMessageModel.to_node_id.is_(None), ChatMessageModel.gateway_id.is_not(None))
            .group_by(
                ChatMessageModel.gateway_id,
                ChatMessageModel.channel_index,
                ChatMessageModel.channel_name,
            )
            .order_by(ChatMessageModel.gateway_id, ChatMessageModel.channel_index)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "gateway_id": r.gateway_id,
                "channel_index": r.channel_index,
                "channel_name": r.channel_name,
                "message_count": r.message_count,
                "last_message_at": r.last_message_at,
            }
            for r in rows
        ]

    async def dm_count_by_gateway(self) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(ChatMessageModel.gateway_id, func.count())
                .where(ChatMessageModel.to_node_id.is_not(None), ChatMessageModel.gateway_id.is_not(None))
                .group_by(ChatMessageModel.gateway_id)
            )
        ).all()
        return {gid: int(n) for gid, n in rows}

    async def dm_count(self) -> int:
        result = await self._session.scalar(
            select(func.count())
            .select_from(ChatMessageModel)
            .where(ChatMessageModel.to_node_id.is_not(None))
        )
        return int(result or 0)

    async def get(self, message_id: int) -> ChatMessage | None:
        m = await self._session.get(ChatMessageModel, message_id)
        return _to_entity(m) if m else None

    async def list_same_packet(self, from_node_id: str, packet_id: int) -> list[ChatMessage]:
        """Todas las filas (una por pasarela) con el mismo remitente y packet_id."""
        rows = await self._session.scalars(
            select(ChatMessageModel).where(
                ChatMessageModel.from_node_id == from_node_id, ChatMessageModel.packet_id == packet_id
            )
        )
        return [_to_entity(r) for r in rows]
