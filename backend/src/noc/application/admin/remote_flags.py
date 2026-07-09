"""Adaptador de estado de sincronización remota de favoritos/ignorados
(M4.1/M4.2, ADR 0019/0020).

Implementa el puerto `RemoteFlagStateReader` (`remote_flag_sync.py`) leyendo
`admin_operations`: sin tabla propia, el estado se deriva del historial de
auditoría ya existente. `remote_flag_sync.py` no conoce esta clase concreta,
solo el Protocol — el día que haga falta una tabla materializada, una caché o
una lectura real del firmware, se sustituye este adaptador sin tocar el
algoritmo de planificación.

Vocabulario de cara al operador: Pendiente/Enviado/Confirmado/Error — nunca
"succeeded_unconfirmed" ni "verificado" (ADR 0019 §2): el firmware no expone
lectura de favoritos/ignorados, así que "Confirmado" solo significa que el
firmware aceptó el AdminMessage (ACK), no que el NOC haya podido releer su
NodeDB.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.admin.remote_flag_sync import FlagAction, FlagType, RemoteFlagKnown, SyncState
from noc.domain.admin.entities import AdminOperation

FLAG_OPERATION_TYPES: dict[FlagType, tuple[str, str]] = {
    "favorite": ("favorite.set", "favorite.remove"),
    "ignored": ("ignored.set", "ignored.remove"),
}
CONTACT_OPERATION_TYPE = "contact.add"

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


def _action_of(op: AdminOperation) -> FlagAction:
    return "set" if op.operation_type.endswith(".set") else "remove"


class AdminOperationRemoteFlagStateReader:
    """Implementación del puerto `RemoteFlagStateReader` sobre `admin_operations`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_known(self, target_node_id: str, flag_type: FlagType) -> list[RemoteFlagKnown]:
        op_types = FLAG_OPERATION_TYPES[flag_type]
        ops = await SqlAdminOperationRepository(self._session).list_by_node_and_types(target_node_id, op_types)

        by_subject: dict[str, list[AdminOperation]] = {}
        for op in ops:  # ya vienen más nuevo primero
            subject = op.params.get("subject_node_id")
            if subject:
                by_subject.setdefault(subject, []).append(op)

        result: list[RemoteFlagKnown] = []
        for subject, subject_ops in by_subject.items():
            latest = subject_ops[0]
            confirmed = next(
                (o for o in subject_ops if _SYNC_STATE_BY_OP_STATUS.get(o.status) == "confirmed"), None
            )
            result.append(
                RemoteFlagKnown(
                    subject_node_id=subject,
                    latest_action=_action_of(latest),
                    sync_state=_SYNC_STATE_BY_OP_STATUS.get(latest.status, "error"),
                    operation_id=latest.id or 0,
                    updated_at=latest.finished_at or latest.started_at or latest.queued_at or latest.created_at,
                    confirmed_action=_action_of(confirmed) if confirmed else None,
                )
            )
        return result
