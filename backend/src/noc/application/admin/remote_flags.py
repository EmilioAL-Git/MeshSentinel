"""Estado de sincronización remota de favoritos/ignorados (M4.1, ADR 0019).

Sin tabla propia: se deriva de la última `AdminOperation` relevante para el
par (target_node_id, subject_node_id). El vocabulario de cara al operador es
deliberadamente Pendiente/Enviado/Confirmado/Error — nunca
"succeeded_unconfirmed" ni "verificado" (ADR 0019 §2): el firmware no expone
lectura de favoritos/ignorados, así que "Confirmado" solo significa que el
firmware aceptó el AdminMessage (ACK), no que el NOC haya podido releer su
NodeDB.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.domain.admin.entities import AdminOperation

FAVORITE_OPERATION_TYPES: tuple[str, ...] = ("favorite.set", "favorite.remove")
IGNORED_OPERATION_TYPES: tuple[str, ...] = ("ignored.set", "ignored.remove")
CONTACT_OPERATION_TYPE = "contact.add"

SyncState = Literal["pending", "sent", "confirmed", "error"]

_SYNC_STATE_BY_OP_STATUS: dict[str, SyncState] = {
    "pending": "pending",
    "queued": "pending",
    "running": "sent",
    "succeeded": "confirmed",
    "succeeded_unconfirmed": "confirmed",
    "verify_failed": "error",
    "failed": "error",
    "timeout": "error",
    "cancelled": "error",
}


@dataclass(slots=True, frozen=True)
class RemoteFlagStatus:
    subject_node_id: str
    desired: bool  # True = "set" (favorito/ignorado), False = "remove"
    sync_state: SyncState
    operation_id: int
    updated_at: datetime | None


def _from_operation(op: AdminOperation) -> RemoteFlagStatus:
    subject = op.params.get("subject_node_id", "")
    desired = op.operation_type.endswith(".set")
    sync_state = _SYNC_STATE_BY_OP_STATUS.get(op.status, "error")
    updated_at = op.finished_at or op.started_at or op.queued_at or op.created_at
    return RemoteFlagStatus(subject, desired, sync_state, op.id or 0, updated_at)


async def _latest_status(
    session: AsyncSession, node_id: str, operation_types: tuple[str, ...], subject_node_id: str | None
) -> RemoteFlagStatus | None:
    ops = await SqlAdminOperationRepository(session).list_by_node_and_types(node_id, operation_types)
    if subject_node_id is not None:
        ops = [o for o in ops if o.params.get("subject_node_id") == subject_node_id]
    return _from_operation(ops[0]) if ops else None


async def get_favorite_status(
    session: AsyncSession, node_id: str, subject_node_id: str | None = None
) -> RemoteFlagStatus | None:
    return await _latest_status(session, node_id, FAVORITE_OPERATION_TYPES, subject_node_id)


async def get_ignored_status(
    session: AsyncSession, node_id: str, subject_node_id: str | None = None
) -> RemoteFlagStatus | None:
    return await _latest_status(session, node_id, IGNORED_OPERATION_TYPES, subject_node_id)
