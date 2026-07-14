from dataclasses import fields
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import (
    AdminBatchModel,
    AdminOperationModel,
    GroupMemberModel,
)
from noc.domain.admin.entities import (
    IN_FLIGHT_STATUSES,
    TERMINAL_STATUSES,
    AdminBatch,
    AdminOperation,
)


def _entity(m: AdminOperationModel) -> AdminOperation:
    return AdminOperation(**{f.name: getattr(m, f.name) for f in fields(AdminOperation)})


class SqlAdminOperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, op: AdminOperation) -> AdminOperation:
        m = AdminOperationModel(
            batch_id=op.batch_id,
            target_node_id=op.target_node_id,
            gateway_id=op.gateway_id,
            operation_type=op.operation_type,
            params=op.params,
            status=op.status,
            priority=op.priority,
            attempts=op.attempts,
            max_attempts=op.max_attempts,
            timeout_seconds=op.timeout_seconds,
            next_attempt_at=op.next_attempt_at,
            created_by=op.created_by,
            actor_type=op.actor_type,
            actor_id=op.actor_id,
            actor_username=op.actor_username,
            actor_display_name=op.actor_display_name,
            created_at=op.created_at or datetime.now(timezone.utc),
            gateway_note=op.gateway_note,
        )
        self._session.add(m)
        await self._session.flush()
        return _entity(m)

    async def get(self, op_id: int) -> AdminOperation | None:
        m = await self._session.get(AdminOperationModel, op_id)
        return _entity(m) if m else None

    async def list_operations(
        self,
        status: str | None,
        node_id: str | None,
        limit: int,
        batch_id: int | None = None,
    ) -> list[AdminOperation]:
        stmt = select(AdminOperationModel).order_by(AdminOperationModel.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(AdminOperationModel.status == status)
        if node_id:
            stmt = stmt.where(AdminOperationModel.target_node_id == node_id)
        if batch_id is not None:
            stmt = stmt.where(AdminOperationModel.batch_id == batch_id)
        rows = await self._session.scalars(stmt)
        return [_entity(r) for r in rows]

    async def list_by_node_and_types(
        self, node_id: str, operation_types: tuple[str, ...], limit: int = 200
    ) -> list[AdminOperation]:
        """Historial reciente de un nodo restringido a ciertos tipos de
        operación, más nuevo primero (M4.1: estado de sync remoto derivado,
        ADR 0019 — sin tabla propia, se deriva de `admin_operations`)."""
        stmt = (
            select(AdminOperationModel)
            .where(
                AdminOperationModel.target_node_id == node_id,
                AdminOperationModel.operation_type.in_(operation_types),
            )
            .order_by(AdminOperationModel.created_at.desc())
            .limit(limit)
        )
        rows = await self._session.scalars(stmt)
        return [_entity(r) for r in rows]

    async def update_fields(self, op_id: int, changes: dict) -> AdminOperation | None:
        m = await self._session.get(AdminOperationModel, op_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        await self._session.flush()
        return _entity(m)

    async def next_dispatchable(self, now: datetime) -> AdminOperation | None:
        """Siguiente pendiente lista para enviar, para una pasarela sin operación
        en vuelo (1 en vuelo por gateway, diseño §4.4)."""
        busy = select(AdminOperationModel.gateway_id).where(
            AdminOperationModel.status.in_(IN_FLIGHT_STATUSES)
        )
        # Un lote pausado retiene sus operaciones pendientes (M2). Las de un
        # lote cancelado ya están en estado cancelled, no necesitan filtro.
        paused_batches = select(AdminBatchModel.id).where(AdminBatchModel.status == "paused")
        stmt = (
            select(AdminOperationModel)
            .where(
                AdminOperationModel.status == "pending",
                AdminOperationModel.gateway_id.not_in(busy),
                (AdminOperationModel.next_attempt_at.is_(None))
                | (AdminOperationModel.next_attempt_at <= now),
                (AdminOperationModel.batch_id.is_(None))
                | (AdminOperationModel.batch_id.not_in(paused_batches)),
            )
            .order_by(AdminOperationModel.priority, AdminOperationModel.created_at)
            .limit(1)
        )
        m = await self._session.scalar(stmt)
        return _entity(m) if m else None

    async def active_counts(self, group_id: int | None = None) -> dict[str, int]:
        """Agregados de operaciones no terminales para HUD/insignias
        (hardening): pending/queued/running por conteo real en BD, nunca
        derivados de una lista con `limit`. Con `group_id`, mismo criterio
        que `scopeOperationsToGroup` de la UI (target dentro del grupo)."""
        stmt = (
            select(AdminOperationModel.status, func.count())
            .where(AdminOperationModel.status.in_(("pending", "queued", "running")))
            .group_by(AdminOperationModel.status)
        )
        if group_id is not None:
            members = select(GroupMemberModel.node_id).where(
                GroupMemberModel.group_id == group_id
            )
            stmt = stmt.where(AdminOperationModel.target_node_id.in_(members))
        counts = {"pending": 0, "queued": 0, "running": 0}
        for status, n in (await self._session.execute(stmt)).all():
            counts[status] = n
        counts["active"] = counts["pending"] + counts["queued"] + counts["running"]
        return counts

    async def count_dispatched_since(self, since: datetime) -> int:
        result = await self._session.scalar(
            select(func.count())
            .select_from(AdminOperationModel)
            .where(AdminOperationModel.queued_at >= since)
        )
        return int(result or 0)

    async def list_expired_in_flight(self, now: datetime, grace_seconds: int) -> list[AdminOperation]:
        rows = await self._session.scalars(
            select(AdminOperationModel).where(AdminOperationModel.status.in_(IN_FLIGHT_STATUSES))
        )
        expired = []
        for m in rows:
            anchor = m.queued_at or m.created_at
            if anchor is None:
                continue
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            if now - anchor > timedelta(seconds=m.timeout_seconds + grace_seconds):
                expired.append(_entity(m))
        return expired


def _batch_entity(m: AdminBatchModel) -> AdminBatch:
    return AdminBatch(**{f.name: getattr(m, f.name) for f in fields(AdminBatch)})


class SqlAdminBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, batch: AdminBatch) -> AdminBatch:
        m = AdminBatchModel(
            name=batch.name,
            operation_type=batch.operation_type,
            params=batch.params,
            node_ids=batch.node_ids,
            scope_description=batch.scope_description,
            status=batch.status,
            created_by=batch.created_by,
            actor_type=batch.actor_type,
            actor_id=batch.actor_id,
            actor_username=batch.actor_username,
            actor_display_name=batch.actor_display_name,
            created_at=batch.created_at or datetime.now(timezone.utc),
            started_at=batch.started_at,
        )
        self._session.add(m)
        await self._session.flush()
        return _batch_entity(m)

    async def get(self, batch_id: int) -> AdminBatch | None:
        m = await self._session.get(AdminBatchModel, batch_id)
        return _batch_entity(m) if m else None

    async def update_fields(self, batch_id: int, changes: dict) -> AdminBatch | None:
        m = await self._session.get(AdminBatchModel, batch_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        await self._session.flush()
        return _batch_entity(m)

    async def list_batches(
        self,
        status: str | None = None,
        operation_type: str | None = None,
        created_by: str | None = None,
        node_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AdminBatch]:
        stmt = select(AdminBatchModel).order_by(AdminBatchModel.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(AdminBatchModel.status == status)
        if operation_type:
            stmt = stmt.where(AdminBatchModel.operation_type == operation_type)
        if created_by:
            stmt = stmt.where(AdminBatchModel.created_by == created_by)
        if since:
            stmt = stmt.where(AdminBatchModel.created_at >= since)
        if until:
            stmt = stmt.where(AdminBatchModel.created_at <= until)
        if node_id:
            containing = select(AdminOperationModel.batch_id).where(
                AdminOperationModel.target_node_id == node_id,
                AdminOperationModel.batch_id.is_not(None),
            )
            stmt = stmt.where(AdminBatchModel.id.in_(containing))
        rows = await self._session.scalars(stmt)
        return [_batch_entity(r) for r in rows]

    async def status_counts(self, batch_id: int) -> dict[str, int]:
        rows = await self._session.execute(
            select(AdminOperationModel.status, func.count())
            .where(AdminOperationModel.batch_id == batch_id)
            .group_by(AdminOperationModel.status)
        )
        return {status: int(count) for status, count in rows}

    async def cancel_pending_operations(self, batch_id: int, now: datetime) -> int:
        """Cancela SOLO lo no iniciado (pending). Una operación queued ya fue
        despachada al gateway y una running está ejecutándose sobre LoRa:
        ninguna de las dos se interrumpe (M2); sus resultados se procesan con
        normalidad y el lote se cierra cuando terminan."""
        rows = await self._session.scalars(
            select(AdminOperationModel).where(
                AdminOperationModel.batch_id == batch_id,
                AdminOperationModel.status == "pending",
            )
        )
        cancelled = 0
        for m in rows:
            m.status = "cancelled"
            m.finished_at = now
            cancelled += 1
        await self._session.flush()
        return cancelled

    async def has_open_operations(self, batch_id: int) -> bool:
        stmt = select(func.count()).select_from(AdminOperationModel).where(
            AdminOperationModel.batch_id == batch_id,
            AdminOperationModel.status.not_in(TERMINAL_STATUSES),
        )
        return int(await self._session.scalar(stmt) or 0) > 0

    async def running_operation(self, batch_id: int) -> AdminOperation | None:
        m = await self._session.scalar(
            select(AdminOperationModel)
            .where(
                AdminOperationModel.batch_id == batch_id,
                AdminOperationModel.status.in_(IN_FLIGHT_STATUSES),
            )
            .limit(1)
        )
        return _entity(m) if m else None
