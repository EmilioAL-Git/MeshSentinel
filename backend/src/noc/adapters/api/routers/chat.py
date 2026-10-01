"""Chat: monitor profesional de TEXT_MESSAGE_APP (no un cliente de mensajería).

Reutiliza `chat_messages`, poblada por el mismo `_on_message` que narra
Actividad 2.0 — este router solo lee. Los nombres de nodo se resuelven en el
cliente (igual que el resto de la consola de Registro) a partir de
`GET /nodes`, para no duplicar esa lógica aquí.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.chat_repositories import SqlChatRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.application.channel_names import merge_channel_names
from noc.domain.chat.entities import ChatMessage

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessageOut(BaseModel):
    id: int
    from_node_id: str
    to_node_id: str | None
    channel_index: int
    channel_name: str | None
    text: str
    gateway_id: str | None
    rssi: int | None
    snr: float | None
    hops_away: int | None
    hop_limit: int | None
    hop_start: int | None
    packet_id: int | None
    direction: str
    received_at: datetime | None

    @classmethod
    def from_entity(cls, m: ChatMessage) -> "ChatMessageOut":
        return cls(**{f: getattr(m, f) for f in cls.model_fields})


class ChatChannelOut(BaseModel):
    channel_index: int
    channel_name: str | None
    message_count: int
    last_message_at: datetime | None


class ChatGatewayChannelsOut(BaseModel):
    gateway_id: str
    channels: list[ChatChannelOut]
    dm_count: int


class ChatChannelsOut(BaseModel):
    channels: list[ChatChannelOut]
    dm_count: int
    by_gateway: list[ChatGatewayChannelsOut] = []


@router.get("/messages", response_model=list[ChatMessageOut])
async def list_messages(
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None, ge=1),
    channel_index: int | None = Query(default=None, ge=0),
    dm_only: bool = False,
    broadcast_only: bool = False,
    node_id: str | None = None,
    gateway_id: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=200),
) -> list[ChatMessageOut]:
    messages = await SqlChatRepository(session).list_messages(
        limit,
        before_id=before_id,
        channel_index=channel_index,
        dm_only=dm_only,
        broadcast_only=broadcast_only,
        node_id=node_id,
        gateway_id=gateway_id,
        q=q,
    )
    names = await _channel_names(session)
    out = []
    for m in messages:
        row = ChatMessageOut.from_entity(m)
        if row.channel_name is None and row.channel_index in names:
            row = row.model_copy(update={"channel_name": names[row.channel_index]})
        out.append(row)
    return out


async def _channel_names(session: SessionDep) -> dict[int, str]:
    return merge_channel_names(await SqlGatewayRepository(session).list_all())


@router.get("/channels", response_model=ChatChannelsOut)
async def list_channels(session: SessionDep) -> ChatChannelsOut:
    """Base del selector "Todos / Canal 0 / Canal 1 / ... / Directos": solo
    canales por los que ha circulado tráfico de verdad, con el nombre real
    (leído del nodo local de cada pasarela, fusionado por prioridad — ver
    `application/channel_names.py`) o `None` si ninguna pasarela lo conoce
    (el cliente muestra "Canal N")."""
    repo = SqlChatRepository(session)
    channels: list[dict[str, Any]] = await repo.list_channels()
    dm_count = await repo.dm_count()
    names = await _channel_names(session)

    gateways = {g.gateway_id: g for g in await SqlGatewayRepository(session).list_all()}
    dm_by_gw = await repo.dm_count_by_gateway()
    grouped: dict[str, list[ChatChannelOut]] = {}
    for c in await repo.list_channels_by_gateway():
        gid = c.pop("gateway_id")
        # Nombre de ESTA pasarela (no el fusionado): cada una tiene su malla.
        own = {
            int(ch["index"]): (ch.get("name") or "").strip()
            for ch in (gateways[gid].channels if gid in gateways else [])
            if ch.get("index") is not None
        }
        c["channel_name"] = own.get(c["channel_index"]) or c["channel_name"]
        grouped.setdefault(gid, []).append(ChatChannelOut(**c))
    by_gateway = [
        ChatGatewayChannelsOut(gateway_id=gid, channels=chs, dm_count=dm_by_gw.get(gid, 0))
        for gid, chs in sorted(grouped.items())
    ]
    return ChatChannelsOut(
        by_gateway=by_gateway,
        channels=[
            ChatChannelOut(**{**c, "channel_name": names.get(c["channel_index"], c["channel_name"])})
            for c in channels
        ],
        dm_count=dm_count,
    )
