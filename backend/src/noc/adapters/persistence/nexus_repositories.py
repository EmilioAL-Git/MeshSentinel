from dataclasses import fields
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import NexusOperationModel, NexusOperationResponseModel
from noc.domain.nexus.entities import NexusOperation, NexusOperationResponse


def _entity(m: NexusOperationModel) -> NexusOperation:
    return NexusOperation(**{f.name: getattr(m, f.name) for f in fields(NexusOperation)})


def _response_entity(m: NexusOperationResponseModel) -> NexusOperationResponse:
    return NexusOperationResponse(**{f.name: getattr(m, f.name) for f in fields(NexusOperationResponse)})


class SqlNexusOperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, op: NexusOperation) -> NexusOperation:
        m = NexusOperationModel(
            gateway_id=op.gateway_id,
            target_kind=op.target_kind,
            target_value=op.target_value,
            command_name=op.command_name,
            args=list(op.args),
            text=op.text,
            destructive=op.destructive,
            requires_save=op.requires_save,
            busy_seconds=op.busy_seconds,
            status=op.status,
            created_by=op.created_by,
            created_at=op.created_at or datetime.now(timezone.utc),
            batch_key=op.batch_key,
            batch_interval_seconds=op.batch_interval_seconds,
        )
        self._session.add(m)
        await self._session.flush()
        return _entity(m)

    async def get(self, op_id: int) -> NexusOperation | None:
        m = await self._session.get(NexusOperationModel, op_id)
        return _entity(m) if m else None

    async def list_operations(
        self, gateway_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[NexusOperation]:
        stmt = select(NexusOperationModel).order_by(NexusOperationModel.created_at.desc()).limit(limit)
        if gateway_id:
            stmt = stmt.where(NexusOperationModel.gateway_id == gateway_id)
        if status:
            stmt = stmt.where(NexusOperationModel.status == status)
        rows = await self._session.scalars(stmt)
        return [_entity(r) for r in rows]

    async def update_fields(self, op_id: int, changes: dict) -> NexusOperation | None:
        m = await self._session.get(NexusOperationModel, op_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        await self._session.flush()
        return _entity(m)

    async def has_active_for_gateway(self, gateway_id: str) -> bool:
        """Comprobación de seguridad antes de borrar un gateway de verdad:
        ¿hay algo pendiente/enviado (esperando respuesta) por esta pasarela
        en la cola Nexus (ADR 0027 §4) ahora mismo?"""
        stmt = (
            select(NexusOperationModel.id)
            .where(
                NexusOperationModel.gateway_id == gateway_id,
                NexusOperationModel.status.in_(("pending", "sent")),
            )
            .limit(1)
        )
        return (await self._session.scalar(stmt)) is not None

    async def list_pending(self, limit: int = 200) -> list[NexusOperation]:
        stmt = (
            select(NexusOperationModel)
            .where(NexusOperationModel.status == "pending")
            .order_by(NexusOperationModel.created_at, NexusOperationModel.id)
            .limit(limit)
        )
        rows = await self._session.scalars(stmt)
        return [_entity(r) for r in rows]

    async def latest_sent_in_batch(self, batch_key: str) -> datetime | None:
        """Última vez que se despachó CUALQUIER operación de este lote
        (ADR 0027 §14) — gating de espaciado entre miembros del lote,
        independiente del `CommandPacer` del núcleo puro (que no espacia
        entre destinos DISTINTOS)."""
        return await self._session.scalar(
            select(func.max(NexusOperationModel.sent_at)).where(
                NexusOperationModel.batch_key == batch_key,
                NexusOperationModel.sent_at.is_not(None),
            )
        )

    async def list_expired_sent(self, now: datetime, base_window_seconds: float) -> list[NexusOperation]:
        """Sin GET de verificación (ADR 0013) ni reporte del gateway (ADR
        0027 §4): una operación "sent" sin respuesta tras su ventana
        (base + tiempo de nodo ocupado) se da por sin respuesta, calculado
        en Python igual que `list_expired_in_flight` del pipeline admin."""
        rows = await self._session.scalars(
            select(NexusOperationModel).where(
                NexusOperationModel.status == "sent", NexusOperationModel.sent_at.is_not(None)
            )
        )
        expired = []
        for m in rows:
            sent_at = m.sent_at
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            deadline = sent_at + timedelta(seconds=base_window_seconds + m.busy_seconds)
            if now >= deadline:
                expired.append(_entity(m))
        return expired


class SqlNexusOperationResponseRepository:
    """Respuestas individuales a operaciones de destino múltiple
    (broadcast/group, ADR 0027 §11) — append-only, una fila por nodo que
    responde."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, response: NexusOperationResponse) -> NexusOperationResponse:
        m = NexusOperationResponseModel(
            operation_id=response.operation_id,
            from_node_id=response.from_node_id,
            received_at=response.received_at or datetime.now(timezone.utc),
            response_text=response.response_text,
            response_kind=response.response_kind,
            response_data=response.response_data,
        )
        self._session.add(m)
        await self._session.flush()
        return _response_entity(m)

    async def list_for_operation(self, operation_id: int, limit: int = 200) -> list[NexusOperationResponse]:
        stmt = (
            select(NexusOperationResponseModel)
            .where(NexusOperationResponseModel.operation_id == operation_id)
            .order_by(NexusOperationResponseModel.received_at)
            .limit(limit)
        )
        rows = await self._session.scalars(stmt)
        return [_response_entity(r) for r in rows]

    async def count_for_operation(self, operation_id: int) -> int:
        result = await self._session.scalar(
            select(func.count()).where(NexusOperationResponseModel.operation_id == operation_id)
        )
        return int(result or 0)
