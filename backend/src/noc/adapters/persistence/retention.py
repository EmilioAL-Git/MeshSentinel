"""Poda por retención y estadísticas de almacenamiento (Ajustes → Datos).

Cada tipo de dato tiene su propio plazo en días (`Settings.retention_*_days`,
editable en runtime; 0 = conservar siempre). La poda borra en lotes con una
transacción propia por lote: en SQLite (un solo escritor) una única DELETE
gigante bloquearía la ingesta durante segundos; así cede el turno entre lotes.
Series temporales y diarios se podan por fecha; las entidades con estado
(alertas, operaciones, lotes) SOLO cuando ya son terminales — nunca se borra
algo que aún está vivo.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.database import Base
from noc.adapters.persistence.models import (
    AdminBatchModel,
    AdminOperationModel,
    AlertModel,
    AuthLoginLogModel,
    ChatMessageModel,
    GatewayModel,
    NeighborModel,
    NexusOperationModel,
    NexusOperationResponseModel,
    NodeModel,
    PositionModel,
    TelemetryModel,
    UserFavoriteModel,
)
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.config import Settings
from noc.domain.admin.entities import BATCH_TERMINAL_STATUSES, TERMINAL_STATUSES
from noc.domain.nexus.entities import TERMINAL_STATUSES as NEXUS_TERMINAL

CHUNK = 5000
NODE_CHUNK = 200


@dataclass(slots=True, frozen=True)
class RetentionTarget:
    key: str  # clave en el resultado y en la tabla de estadísticas
    label: str
    setting: str  # campo de Settings con los días
    tables: tuple[str, ...]  # tablas que cubre (para la vista de almacenamiento)


TARGETS: tuple[RetentionTarget, ...] = (
    RetentionTarget("telemetry", "Telemetría", "retention_telemetry_days", ("node_telemetry",)),
    RetentionTarget("positions", "Posiciones", "retention_positions_days", ("node_positions",)),
    RetentionTarget("neighbors", "Vecinos", "retention_neighbors_days", ("node_neighbors",)),
    RetentionTarget("chat", "Mensajes de chat", "retention_chat_days", ("chat_messages",)),
    RetentionTarget("alerts", "Alertas resueltas", "retention_alerts_days", ("alerts",)),
    RetentionTarget(
        "admin", "Operaciones y lotes de administración", "retention_admin_days",
        ("admin_operations", "admin_batches"),
    ),
    RetentionTarget(
        "nexus", "Operaciones Nexus", "retention_nexus_days",
        ("nexus_operations", "nexus_operation_responses"),
    ),
    RetentionTarget("login_log", "Registro de accesos", "retention_login_log_days", ("auth_login_log",)),
    RetentionTarget("nodes", "Nodos sin actividad", "retention_nodes_days", ("nodes",)),
)

TABLE_LABELS: dict[str, str] = {
    "nodes": "Nodos",
    "node_telemetry": "Telemetría",
    "node_positions": "Posiciones",
    "node_neighbors": "Vecinos (NeighborInfo)",
    "node_gateway_links": "Enlaces nodo↔pasarela",
    "chat_messages": "Mensajes de chat",
    "alerts": "Alertas",
    "admin_operations": "Operaciones de administración",
    "admin_batches": "Lotes de administración",
    "nexus_operations": "Operaciones Nexus",
    "nexus_operation_responses": "Respuestas Nexus",
    "activity_log": "Registro de actividad",
    "auth_login_log": "Registro de accesos",
    "auth_sessions": "Sesiones",
}

# Columna temporal "más antigua" por tabla, para mostrar desde cuándo hay datos
OLDEST_COLUMN: dict[str, str] = {
    "nodes": "first_seen_at",
    "node_telemetry": "received_at",
    "node_positions": "received_at",
    "node_neighbors": "received_at",
    "chat_messages": "received_at",
    "alerts": "fired_at",
    "admin_operations": "created_at",
    "admin_batches": "created_at",
    "nexus_operations": "created_at",
    "nexus_operation_responses": "received_at",
    "activity_log": "created_at",
    "auth_login_log": "created_at",
}


def _cutoff(days: int, now: datetime) -> datetime | None:
    return now - timedelta(days=days) if days > 0 else None


async def _delete_in_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    model: Any,
    *conditions: Any,
) -> int:
    """DELETE por lotes de `CHUNK` ids, una transacción por lote."""
    total = 0
    while True:
        async with session_factory() as session:
            ids = list(
                (await session.scalars(select(model.id).where(*conditions).limit(CHUNK))).all()
            )
            if not ids:
                return total
            await session.execute(delete(model).where(model.id.in_(ids)))
            await session.commit()
        total += len(ids)
        await asyncio.sleep(0)  # cede el turno al resto de tareas


async def _prune_nexus(session_factory: async_sessionmaker[AsyncSession], cutoff: datetime) -> int:
    total = 0
    cond = (
        NexusOperationModel.status.in_(NEXUS_TERMINAL),
        func.coalesce(
            NexusOperationModel.response_at, NexusOperationModel.sent_at, NexusOperationModel.created_at
        )
        < cutoff,
    )
    while True:
        async with session_factory() as session:
            ids = list(
                (await session.scalars(select(NexusOperationModel.id).where(*cond).limit(CHUNK))).all()
            )
            if not ids:
                return total
            await session.execute(
                delete(NexusOperationResponseModel).where(
                    NexusOperationResponseModel.operation_id.in_(ids)
                )
            )
            await session.execute(delete(NexusOperationModel).where(NexusOperationModel.id.in_(ids)))
            await session.commit()
        total += len(ids)
        await asyncio.sleep(0)


async def _prune_admin(session_factory: async_sessionmaker[AsyncSession], cutoff: datetime) -> int:
    total = await _delete_in_chunks(
        session_factory,
        AdminOperationModel,
        AdminOperationModel.status.in_(TERMINAL_STATUSES),
        func.coalesce(AdminOperationModel.finished_at, AdminOperationModel.created_at) < cutoff,
    )
    # Lotes terminados sin operaciones restantes (FK admin_operations.batch_id)
    total += await _delete_in_chunks(
        session_factory,
        AdminBatchModel,
        AdminBatchModel.status.in_(BATCH_TERMINAL_STATUSES),
        func.coalesce(AdminBatchModel.finished_at, AdminBatchModel.created_at) < cutoff,
        ~exists().where(AdminOperationModel.batch_id == AdminBatchModel.id),
    )
    return total


async def _prune_nodes(session_factory: async_sessionmaker[AsyncSession], cutoff: datetime) -> int:
    """Nodos sin actividad desde `cutoff`. Excluye favoritos de cualquier
    usuario y los nodos locales de una pasarela (borrarlos rompería la
    cobertura/enlaces de esa pasarela)."""
    total = 0
    while True:
        async with session_factory() as session:
            ids = list(
                (
                    await session.scalars(
                        select(NodeModel.id)
                        .where(
                            NodeModel.last_seen_at < cutoff,
                            ~exists().where(UserFavoriteModel.node_id == NodeModel.id),
                            ~exists().where(GatewayModel.local_node_id == NodeModel.id),
                        )
                        .limit(NODE_CHUNK)
                    )
                ).all()
            )
            if not ids:
                return total
            deleted = await SqlNodeRepository(session).delete_bulk(ids)
            await session.commit()
        total += deleted
        await asyncio.sleep(0)


async def prune_all(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, now: datetime | None = None
) -> dict[str, int]:
    """Aplica TODAS las políticas. Devuelve filas borradas por clave de
    `TARGETS` (solo las políticas activas). Los nodos van los últimos: su
    borrado arrastra la historia propia que las demás podas ya habrían
    recortado igualmente."""
    now = now or datetime.now(timezone.utc)
    result: dict[str, int] = {}

    async def run(key: str, days_field: str, op: Any) -> None:
        cutoff = _cutoff(int(getattr(settings, days_field)), now)
        if cutoff is not None:
            result[key] = await op(cutoff)

    def simple(model: Any, column: Any, *extra: Any) -> Any:
        return lambda cutoff: _delete_in_chunks(session_factory, model, column < cutoff, *extra)

    await run("telemetry", "retention_telemetry_days", simple(TelemetryModel, TelemetryModel.received_at))
    await run("positions", "retention_positions_days", simple(PositionModel, PositionModel.received_at))
    await run("neighbors", "retention_neighbors_days", simple(NeighborModel, NeighborModel.received_at))
    await run("chat", "retention_chat_days", simple(ChatMessageModel, ChatMessageModel.received_at))
    await run(
        "alerts",
        "retention_alerts_days",
        simple(AlertModel, AlertModel.resolved_at, AlertModel.status == "resolved"),
    )
    await run("admin", "retention_admin_days", lambda c: _prune_admin(session_factory, c))
    await run("nexus", "retention_nexus_days", lambda c: _prune_nexus(session_factory, c))
    await run(
        "login_log", "retention_login_log_days", simple(AuthLoginLogModel, AuthLoginLogModel.created_at)
    )
    await run("nodes", "retention_nodes_days", lambda c: _prune_nodes(session_factory, c))
    return result


# ── Estadísticas de almacenamiento ───────────────────────────────────────


@dataclass(slots=True)
class TableStats:
    table: str
    label: str
    rows: int
    bytes: int | None
    oldest: datetime | None


@dataclass(slots=True)
class StorageStats:
    engine: str
    total_bytes: int | None
    tables: list[TableStats]


async def _table_bytes(session: AsyncSession, dialect: str, table: str) -> int | None:
    try:
        if dialect == "postgresql":
            return (
                await session.execute(
                    text("SELECT pg_total_relation_size(CAST(:t AS regclass))"), {"t": table}
                )
            ).scalar_one()
        if dialect == "sqlite":
            return (
                await session.execute(text("SELECT SUM(pgsize) FROM dbstat WHERE name = :t"), {"t": table})
            ).scalar_one()
    except Exception:  # dbstat no compilado en este SQLite, permisos…
        await session.rollback()
    return None


async def _total_bytes(session: AsyncSession, dialect: str) -> int | None:
    try:
        if dialect == "postgresql":
            return (await session.execute(text("SELECT pg_database_size(current_database())"))).scalar_one()
        if dialect == "sqlite":
            pages = (await session.execute(text("PRAGMA page_count"))).scalar_one()
            size = (await session.execute(text("PRAGMA page_size"))).scalar_one()
            return int(pages) * int(size)
    except Exception:
        await session.rollback()
    return None


async def storage_stats(session: AsyncSession) -> StorageStats:
    dialect = session.get_bind().dialect.name
    tables: list[TableStats] = []
    for table in Base.metadata.sorted_tables:
        rows = (await session.execute(select(func.count()).select_from(table))).scalar_one()
        oldest = None
        col = OLDEST_COLUMN.get(table.name)
        if col is not None and rows:
            oldest = (await session.execute(select(func.min(table.c[col])))).scalar_one()
            if oldest is not None and oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
        tables.append(
            TableStats(
                table=table.name,
                label=TABLE_LABELS.get(table.name, table.name),
                rows=int(rows),
                bytes=await _table_bytes(session, dialect, table.name),
                oldest=oldest,
            )
        )
    tables.sort(key=lambda t: (t.bytes or 0, t.rows), reverse=True)
    return StorageStats(engine=dialect, total_bytes=await _total_bytes(session, dialect), tables=tables)
