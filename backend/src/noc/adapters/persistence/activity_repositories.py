"""Persistencia del diario operativo (Registro, fase de hardening).

Guarda y devuelve envelopes `activity.event` completos: la fila es solo un
contenedor indexable del mismo JSON que viaja por el WebSocket, para que el
frontend siembre su buffer con el parser que ya tiene (`toEntry`).
"""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Text, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import ActivityLogModel, GroupMemberModel

SCHEMA_VERSION = 1


def _like_pattern(s: str) -> str:
    """Escapa un literal para usarlo dentro de LIKE ... ESCAPE '\\\\'."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            ts = datetime.fromisoformat(value)
            return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _to_envelope(row: ActivityLogModel) -> dict[str, Any]:
    created = row.created_at
    if created.tzinfo is None:  # SQLite devuelve naive; el sistema persiste UTC
        created = created.replace(tzinfo=timezone.utc)
    return {
        "log_id": row.id,
        "schema_version": SCHEMA_VERSION,
        "event_type": "activity.event",
        "event_id": row.event_id,
        "gateway_id": row.gateway_id,
        "timestamp": created.isoformat(),
        "payload": row.payload,
    }


class SqlActivityLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, envelopes: list[dict[str, Any]]) -> None:
        for env in envelopes:
            payload = env.get("payload") or {}
            self._session.add(
                ActivityLogModel(
                    event_id=str(env.get("event_id") or ""),
                    gateway_id=env.get("gateway_id"),
                    node_id=payload.get("node_id"),
                    source=str(payload.get("source") or "system"),
                    severity=str(payload.get("severity") or "info"),
                    internal_type=payload.get("internal_type"),
                    created_at=_parse_ts(env.get("timestamp")),
                    payload=payload,
                )
            )
        await self._session.flush()

    async def list_recent(
        self,
        limit: int,
        before_id: int | None = None,
        node_id: str | None = None,
        source: str | None = None,
        gateway_id: str | None = None,
        group_id: int | None = None,
        q: str | None = None,
        internal_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Envelopes más recientes primero (mismo orden que el feed en vivo).

        Filtros de servidor (consola profesional del Registro): por pasarela,
        por grupo (misma regla que la UI: los eventos sin nodo — pasarela,
        sistema — siempre son visibles) y búsqueda de texto libre sobre el
        payload completo (LOWER + LIKE sobre el JSON serializado: portable
        entre PostgreSQL y SQLite, sin SQL dialectal)."""
        stmt = select(ActivityLogModel).order_by(ActivityLogModel.id.desc()).limit(limit)
        if before_id is not None:
            stmt = stmt.where(ActivityLogModel.id < before_id)
        if node_id:
            stmt = stmt.where(ActivityLogModel.node_id == node_id)
        if source:
            stmt = stmt.where(ActivityLogModel.source == source)
        if gateway_id:
            stmt = stmt.where(ActivityLogModel.gateway_id == gateway_id)
        if internal_type:
            stmt = stmt.where(ActivityLogModel.internal_type == internal_type)
        if group_id is not None:
            members = select(GroupMemberModel.node_id).where(
                GroupMemberModel.group_id == group_id
            )
            stmt = stmt.where(
                or_(ActivityLogModel.node_id.is_(None), ActivityLogModel.node_id.in_(members))
            )
        if q:
            # El JSON persistido puede llevar los no-ASCII escapados
            # (json.dumps con ensure_ascii, el default de SQLAlchemy):
            # "Posición" se guarda como "Posici\\u00f3n". Se busca tanto la
            # forma cruda como la escapada para que la búsqueda funcione con
            # acentos con cualquiera de las dos serializaciones. OJO LIKE:
            # el patrón escapado contiene backslashes — hay que declarar
            # ESCAPE explícito (portable PG/SQLite) y doblar los literales,
            # o PostgreSQL interpreta `\u` como secuencia de escape del LIKE.
            lowered = q.lower()
            escaped = json.dumps(lowered, ensure_ascii=True)[1:-1].lower()
            haystack = func.lower(cast(ActivityLogModel.payload, Text))
            conds = [haystack.like(f"%{_like_pattern(lowered)}%", escape="\\")]
            if escaped != lowered:
                conds.append(haystack.like(f"%{_like_pattern(escaped)}%", escape="\\"))
            stmt = stmt.where(or_(*conds))
        rows = await self._session.scalars(stmt)
        return [_to_envelope(r) for r in rows]

    async def count(self) -> int:
        result = await self._session.scalar(select(func.count()).select_from(ActivityLogModel))
        return int(result or 0)

    async def prune_to(self, max_rows: int) -> int:
        """Conserva las `max_rows` filas más recientes; devuelve las borradas.

        Poda por id (autoincremental = orden de inserción): una sola pasada,
        sin ventanas — suficiente para un tope de tamaño, no un TTL.
        """
        if max_rows <= 0:
            return 0
        threshold = await self._session.scalar(
            select(ActivityLogModel.id).order_by(ActivityLogModel.id.desc()).offset(max_rows).limit(1)
        )
        if threshold is None:
            return 0
        result = await self._session.execute(
            delete(ActivityLogModel).where(ActivityLogModel.id <= threshold)
        )
        return int(result.rowcount or 0)
