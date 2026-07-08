from dataclasses import fields
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import AdminOperationModel
from noc.domain.admin.entities import IN_FLIGHT_STATUSES, AdminOperation


def _entity(m: AdminOperationModel) -> AdminOperation:
    return AdminOperation(**{f.name: getattr(m, f.name) for f in fields(AdminOperation)})


class SqlAdminOperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, op: AdminOperation) -> AdminOperation:
        m = AdminOperationModel(
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
            created_at=op.created_at or datetime.now(timezone.utc),
        )
        self._session.add(m)
        await self._session.flush()
        return _entity(m)

    async def get(self, op_id: int) -> AdminOperation | None:
        m = await self._session.get(AdminOperationModel, op_id)
        return _entity(m) if m else None

    async def list_operations(
        self, status: str | None, node_id: str | None, limit: int
    ) -> list[AdminOperation]:
        stmt = select(AdminOperationModel).order_by(AdminOperationModel.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(AdminOperationModel.status == status)
        if node_id:
            stmt = stmt.where(AdminOperationModel.target_node_id == node_id)
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
        stmt = (
            select(AdminOperationModel)
            .where(
                AdminOperationModel.status == "pending",
                AdminOperationModel.gateway_id.not_in(busy),
                (AdminOperationModel.next_attempt_at.is_(None))
                | (AdminOperationModel.next_attempt_at <= now),
            )
            .order_by(AdminOperationModel.priority, AdminOperationModel.created_at)
            .limit(1)
        )
        m = await self._session.scalar(stmt)
        return _entity(m) if m else None

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
