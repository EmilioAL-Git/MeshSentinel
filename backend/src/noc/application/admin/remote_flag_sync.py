"""Planificación de sincronización de favoritos/ignorados remotos (M4.2, ADR 0019/0020).

Núcleo puro e independiente de cómo se conoce el estado remoto: depende
únicamente del puerto `RemoteFlagStateReader`. Hoy la única implementación lee
`admin_operations` (`remote_flags.py`), pero el algoritmo no lo sabe — podrá
sustituirse en el futuro por una tabla materializada, una caché o una lectura
real del firmware sin tocar este módulo.

Dos caminos deliberadamente distintos (no comparten decisión, solo el puerto
de lectura):
- `compute_sync_plan`: reconciliación completa contra el último estado
  confirmado — solo genera lo necesario para alcanzar el estado deseado.
- `compute_resend_plan`: reenvío mecánico de lo atascado (pending/error), sin
  recalcular ningún objetivo — reemite tal cual la última acción pedida.

El plan es un modelo intermedio (`RemoteFlagSyncPlan`) reutilizable para
simulación/preview/estadísticas antes de convertirse, en un segundo paso
(`to_planned_operations`), en `PlannedOperation` concretas del Batch Engine.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from noc.application.admin.batches import PlannedOperation
from noc.application.admin.registry import validate_operation

FlagType = Literal["favorite", "ignored"]
SyncState = Literal["pending", "sent", "confirmed", "error"]
FlagAction = Literal["set", "remove"]
PlanItemKind = Literal["ADD", "REMOVE", "CONTACT_ADD"]


@dataclass(slots=True, frozen=True)
class RemoteFlagKnown:
    """Último estado conocido de un `subject_node_id` para un `(target, flag_type)`."""

    subject_node_id: str
    latest_action: FlagAction
    sync_state: SyncState
    operation_id: int
    updated_at: datetime | None
    confirmed_action: FlagAction | None


class RemoteFlagStateReader(Protocol):
    """Puerto: cómo se conoce el estado remoto. `remote_flag_sync` no conoce
    la implementación (hoy: admin_operations; mañana: lo que sea)."""

    async def list_known(self, target_node_id: str, flag_type: FlagType) -> list[RemoteFlagKnown]: ...


@dataclass(slots=True, frozen=True)
class RemoteFlagPlanItem:
    kind: PlanItemKind
    flag_type: FlagType
    target_node_id: str
    subject_node_id: str
    reason: str
    # Preparado para Multi-Gateway (siempre None en esta fase): permitirá en
    # el futuro enrutar por una pasarela distinta a la registrada del target.
    target_gateway_id: str | None = None


@dataclass(slots=True, frozen=True)
class RemoteFlagSyncPlan:
    target_node_id: str
    flag_type: FlagType
    items: list[RemoteFlagPlanItem] = field(default_factory=list)


async def compute_sync_plan(
    reader: RemoteFlagStateReader,
    target_node_id: str,
    flag_type: FlagType,
    send_contact: bool = False,
) -> RemoteFlagSyncPlan:
    """Reconciliación: compara el estado deseado (última acción pedida por
    subject, confirmada o no) contra el último estado CONFIRMADO conocido.
    Si coinciden, no genera nada — nunca reenvía una operación redundante."""
    known = await reader.list_known(target_node_id, flag_type)
    items: list[RemoteFlagPlanItem] = []
    for k in known:
        if k.confirmed_action == k.latest_action:
            continue
        kind: PlanItemKind = "ADD" if k.latest_action == "set" else "REMOVE"
        if send_contact and kind == "ADD":
            items.append(
                RemoteFlagPlanItem(
                    "CONTACT_ADD", flag_type, target_node_id, k.subject_node_id,
                    reason="ficha de contacto previa a favorito/ignorado",
                )
            )
        reason = (
            f"remoto no coincide con lo deseado (confirmado: {k.confirmed_action or 'ninguno'})"
        )
        items.append(RemoteFlagPlanItem(kind, flag_type, target_node_id, k.subject_node_id, reason))
    return RemoteFlagSyncPlan(target_node_id, flag_type, items)


async def compute_resend_plan(
    reader: RemoteFlagStateReader,
    target_node_id: str,
    flag_type: FlagType,
) -> RemoteFlagSyncPlan:
    """Reenvío mecánico: no compara nada contra un objetivo, solo reemite la
    MISMA acción de cada elemento actualmente atascado (pending/error). Nunca
    toca los ya confirmados."""
    known = await reader.list_known(target_node_id, flag_type)
    items = [
        RemoteFlagPlanItem(
            "ADD" if k.latest_action == "set" else "REMOVE",
            flag_type,
            target_node_id,
            k.subject_node_id,
            reason=f"reenvío de operación atascada (estado: {k.sync_state})",
        )
        for k in known
        if k.sync_state in ("pending", "error")
    ]
    return RemoteFlagSyncPlan(target_node_id, flag_type, items)


def to_planned_operations(
    plan: RemoteFlagSyncPlan,
    target_gateway_id: str,
    contact_data_by_subject: dict[str, dict[str, Any]] | None = None,
) -> list[PlannedOperation]:
    """Segundo paso: convierte el plan (modelo intermedio) en operaciones
    concretas ya validadas por el registro. Aquí, y solo aquí, se resuelve la
    pasarela real de ejecución (hoy siempre la del target; `target_gateway_id`
    del propio item queda reservado para Multi-Gateway futuro)."""
    contact_data_by_subject = contact_data_by_subject or {}
    ops: list[PlannedOperation] = []
    for item in plan.items:
        if item.kind == "CONTACT_ADD":
            op_type = "contact.add"
            params = validate_operation(
                op_type,
                {"subject_node_id": item.subject_node_id, **contact_data_by_subject.get(item.subject_node_id, {})},
            )
        else:
            op_type = f"{item.flag_type}.{'set' if item.kind == 'ADD' else 'remove'}"
            params = validate_operation(op_type, {"subject_node_id": item.subject_node_id})
        ops.append(PlannedOperation(item.target_node_id, target_gateway_id, op_type, params))
    return ops
