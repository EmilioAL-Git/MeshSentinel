from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.activity import activity
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.admin.batches import PlannedOperation
from noc.application.admin.registry import OPERATIONS, validate_operation
from noc.application.admin.remote_flags import AdminOperationRemoteFlagStateReader
from noc.application.admin.remote_flag_sync import (
    RemoteFlagKnown,
    RemoteFlagSyncPlan,
    compute_resend_plan,
    compute_sync_plan,
    to_planned_operations,
)
from noc.config import get_settings
from noc.domain.admin.entities import AdminOperation

router = APIRouter(prefix="/admin", tags=["admin"])


class ParamFieldOut(BaseModel):
    name: str
    kind: str
    required: bool
    max_length: int | None
    minimum: float | None
    maximum: float | None


class CapabilityOut(BaseModel):
    operation_type: str
    description: str
    kind: str
    allow_bulk: bool
    destructive: bool
    required_role: str
    requires_confirmation: bool
    param_choices: dict[str, list[str]]
    param_fields: list[ParamFieldOut]
    ack_only: bool


class OperationIn(BaseModel):
    node_id: str = Field(pattern=r"^![0-9a-f]{8}$")
    operation_type: str
    params: dict[str, Any] = {}
    timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    max_attempts: int | None = Field(default=None, ge=1, le=10)


class OperationOut(BaseModel):
    id: int
    batch_id: int | None
    target_node_id: str
    gateway_id: str
    operation_type: str
    params: dict[str, Any]
    status: Literal[
        "pending",
        "queued",
        "running",
        "succeeded",
        "succeeded_unconfirmed",
        "verify_failed",
        "failed",
        "timeout",
        "cancelled",
    ]
    priority: int
    attempts: int
    max_attempts: int
    timeout_seconds: int
    result: dict[str, Any] | None
    error: str | None
    created_by: str
    created_at: datetime | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None

    @classmethod
    def from_entity(cls, op: AdminOperation) -> "OperationOut":
        return cls(**{f: getattr(op, f) for f in cls.model_fields})


@router.get("/capabilities", response_model=list[CapabilityOut])
async def capabilities() -> list[CapabilityOut]:
    return [
        CapabilityOut(**asdict(spec), requires_confirmation=spec.requires_confirmation)
        for spec in OPERATIONS.values()
    ]


@router.post("/operations", response_model=OperationOut, status_code=201)
async def create_operation(body: OperationIn, session: SessionDep) -> OperationOut:
    settings = get_settings()
    try:
        params = validate_operation(body.operation_type, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # El SELECT del nodo ya abre la transacción implícita de la sesión, por lo
    # que aquí NO puede usarse session.begin(): se cierra con commit()
    node = await SqlNodeRepository(session).get(body.node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found in registry")
    if not node.gateway_id:
        raise HTTPException(status_code=409, detail="Node has no known gateway to route through")

    op = await SqlAdminOperationRepository(session).create(
        AdminOperation(
            target_node_id=body.node_id,
            gateway_id=node.gateway_id,
            operation_type=body.operation_type,
            params=params,
            timeout_seconds=body.timeout_seconds or settings.admin_default_timeout_seconds,
            max_attempts=body.max_attempts or settings.admin_max_attempts,
            created_by="admin",  # RBAC futuro: el campo ya viaja (diseño §8)
        )
    )
    await session.commit()
    await activity.operation(op, "created")
    return OperationOut.from_entity(op)


@router.get("/operations", response_model=list[OperationOut])
async def list_operations(
    session: SessionDep,
    status: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[OperationOut]:
    ops = await SqlAdminOperationRepository(session).list_operations(status, node_id, limit)
    return [OperationOut.from_entity(o) for o in ops]


@router.get("/operations/{op_id}", response_model=OperationOut)
async def get_operation(op_id: int, session: SessionDep) -> OperationOut:
    op = await SqlAdminOperationRepository(session).get(op_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return OperationOut.from_entity(op)


@router.post("/operations/{op_id}/cancel", response_model=OperationOut)
async def cancel_operation(op_id: int, session: SessionDep) -> OperationOut:
    async with session.begin():
        repo = SqlAdminOperationRepository(session)
        op = await repo.get(op_id)
        if op is None:
            raise HTTPException(status_code=404, detail="Operation not found")
        if op.status not in ("pending", "queued"):
            # Lo ya enviado a LoRa no se puede retirar (diseño §4.3)
            raise HTTPException(status_code=409, detail=f"Cannot cancel operation in status '{op.status}'")
        from datetime import timezone

        op = await repo.update_fields(op_id, {"status": "cancelled", "finished_at": datetime.now(timezone.utc)})
    assert op is not None
    return OperationOut.from_entity(op)


@router.post("/operations/{op_id}/retry", response_model=OperationOut)
async def retry_operation(op_id: int, session: SessionDep) -> OperationOut:
    async with session.begin():
        repo = SqlAdminOperationRepository(session)
        op = await repo.get(op_id)
        if op is None:
            raise HTTPException(status_code=404, detail="Operation not found")
        if op.status not in ("failed", "timeout", "cancelled"):
            raise HTTPException(status_code=409, detail=f"Cannot retry operation in status '{op.status}'")
        op = await repo.update_fields(
            op_id,
            {
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": None,
                "error": None,
                "result": None,
                "finished_at": None,
                "duration_ms": None,
            },
        )
    assert op is not None
    return OperationOut.from_entity(op)


# ── Favoritos/ignorados remotos (M4.1, ADR 0019) ─────────────────────────────
# Sin pantalla nueva: estas rutas alimentan la sección dedicada en el detalle
# de nodo del frontend. Encolar SIEMPRE pasa por BatchService.create_planned
# (ADR 0016 §5, ADR 0019 §5), incluso para un único nodo — es el caso trivial
# de lo que en una fase futura serán lotes de N nodos, sin rediseño.


class RemoteFlagKnownOut(BaseModel):
    subject_node_id: str
    subject_display_name: str | None
    latest_action: Literal["set", "remove"]
    sync_state: Literal["pending", "sent", "confirmed", "error"]
    operation_id: int
    updated_at: datetime | None

    @classmethod
    def from_known(cls, k: RemoteFlagKnown, display_name: str | None) -> "RemoteFlagKnownOut":
        return cls(
            subject_node_id=k.subject_node_id,
            subject_display_name=display_name,
            latest_action=k.latest_action,
            sync_state=k.sync_state,
            operation_id=k.operation_id,
            updated_at=k.updated_at,
        )


class RemoteFlagQueueIn(BaseModel):
    flag_type: Literal["favorite", "ignored"]
    action: Literal["set", "remove"]
    subject_node_id: str = Field(pattern=r"^![0-9a-f]{8}$")
    # Ficha de contacto previa (ADR 0019 §4): desactivada por defecto, nunca
    # automática — el operador la activa cuando sospecha que el nodo destino
    # no conoce todavía al nodo sujeto.
    send_contact: bool = False


class RemoteFlagQueueOut(BaseModel):
    batch_id: int
    operation_type: str
    node_ids: list[str]


class RemoteFlagSyncIn(BaseModel):
    flag_type: Literal["favorite", "ignored"]
    send_contact: bool = False


class RemoteFlagSyncOut(BaseModel):
    batch_id: int | None
    operation_type: str
    node_ids: list[str]
    items: int


@router.get("/remote-flags/{node_id}/known", response_model=list[RemoteFlagKnownOut])
async def remote_flags_known(
    node_id: str, session: SessionDep, flag_type: Literal["favorite", "ignored"] = Query(...)
) -> list[RemoteFlagKnownOut]:
    """Lista completa de sujetos conocidos (favoritos o ignorados) para este
    nodo destino, con su estado de sincronización derivado de admin_operations
    (M4.2, ADR 0020)."""
    reader = AdminOperationRemoteFlagStateReader(session)
    known = await reader.list_known(node_id, flag_type)
    node_repo = SqlNodeRepository(session)
    out: list[RemoteFlagKnownOut] = []
    for k in sorted(known, key=lambda k: k.subject_node_id):
        subject = await node_repo.get(k.subject_node_id)
        name = (subject.long_name or subject.short_name) if subject else None
        out.append(RemoteFlagKnownOut.from_known(k, name))
    return out


@router.post("/remote-flags/{node_id}/queue", response_model=RemoteFlagQueueOut, status_code=201)
async def queue_remote_flag(
    node_id: str, body: RemoteFlagQueueIn, request: Request, session: SessionDep
) -> RemoteFlagQueueOut:
    if body.subject_node_id == node_id:
        raise HTTPException(status_code=422, detail="subject_node_id must differ from node_id")

    node_repo = SqlNodeRepository(session)
    target = await node_repo.get(node_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Node not found in registry")
    if not target.gateway_id:
        raise HTTPException(status_code=409, detail="Node has no known gateway to route through")
    subject = await node_repo.get(body.subject_node_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject node not found in registry")

    op_type = f"{body.flag_type}.{body.action}"
    try:
        flag_params = validate_operation(op_type, {"subject_node_id": body.subject_node_id})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    planned = [PlannedOperation(node_id, target.gateway_id, op_type, flag_params)]
    if body.send_contact:
        contact_params = validate_operation(
            "contact.add",
            {
                "subject_node_id": subject.node_id,
                "long_name": subject.long_name,
                "short_name": subject.short_name,
                "hw_model": subject.hw_model,
                "public_key": subject.public_key,
            },
        )
        # La ficha de contacto va primero: el nodo destino debe conocer al
        # sujeto antes de que el favorite/ignored lo referencie (ADR 0019 §4).
        planned.insert(0, PlannedOperation(node_id, target.gateway_id, "contact.add", contact_params))

    verb = "Marcar" if body.action == "set" else "Quitar"
    name = (
        f"{verb} {body.flag_type} remoto: "
        f"{subject.short_name or subject.node_id} → {target.short_name or target.node_id}"
    )
    batch = await request.app.state.batches.create_planned(
        name=name,
        operation_type=op_type,
        params=flag_params,
        planned=planned,
        scope_description={
            "remote_flag": body.flag_type,
            "action": body.action,
            "subject_node_id": body.subject_node_id,
            "send_contact": body.send_contact,
        },
        created_by="admin",
    )
    assert batch.id is not None
    return RemoteFlagQueueOut(batch_id=batch.id, operation_type=op_type, node_ids=batch.node_ids)


async def _resolve_target(node_id: str, session: SessionDep):
    node_repo = SqlNodeRepository(session)
    target = await node_repo.get(node_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Node not found in registry")
    if not target.gateway_id:
        raise HTTPException(status_code=409, detail="Node has no known gateway to route through")
    return target


async def _contact_data_for_plan(session: SessionDep, plan: RemoteFlagSyncPlan) -> dict[str, dict[str, Any]]:
    node_repo = SqlNodeRepository(session)
    subjects = {item.subject_node_id for item in plan.items if item.kind == "CONTACT_ADD"}
    out: dict[str, dict[str, Any]] = {}
    for subject_id in subjects:
        subject = await node_repo.get(subject_id)
        if subject is not None:
            out[subject_id] = {
                "long_name": subject.long_name,
                "short_name": subject.short_name,
                "hw_model": subject.hw_model,
                "public_key": subject.public_key,
            }
    return out


@router.post("/remote-flags/{node_id}/sync", response_model=RemoteFlagSyncOut, status_code=201)
async def sync_remote_flags(
    node_id: str, body: RemoteFlagSyncIn, request: Request, session: SessionDep
) -> RemoteFlagSyncOut:
    """Reconciliación completa (M4.2): compara el estado deseado (última
    acción pedida por sujeto) contra el último estado CONFIRMADO conocido y
    encola en un único lote solo las operaciones necesarias — nunca reenvía
    lo ya confirmado."""
    target = await _resolve_target(node_id, session)
    reader = AdminOperationRemoteFlagStateReader(session)
    plan = await compute_sync_plan(reader, node_id, body.flag_type, send_contact=body.send_contact)
    if not plan.items:
        return RemoteFlagSyncOut(batch_id=None, operation_type=f"{body.flag_type}.sync", node_ids=[], items=0)

    contact_data = await _contact_data_for_plan(session, plan)
    planned = to_planned_operations(plan, target.gateway_id, contact_data)
    batch = await request.app.state.batches.create_planned(
        name=f"Sincronizar {body.flag_type} remoto: {target.short_name or target.node_id}",
        operation_type=f"{body.flag_type}.sync",
        params={},
        planned=planned,
        scope_description={"remote_flag_sync": body.flag_type, "target_node_id": node_id},
        created_by="admin",
    )
    assert batch.id is not None
    return RemoteFlagSyncOut(
        batch_id=batch.id, operation_type=f"{body.flag_type}.sync", node_ids=batch.node_ids, items=len(plan.items)
    )


@router.post("/remote-flags/{node_id}/resend-pending", response_model=RemoteFlagSyncOut, status_code=201)
async def resend_pending_remote_flags(
    node_id: str, body: RemoteFlagSyncIn, request: Request, session: SessionDep
) -> RemoteFlagSyncOut:
    """Reenvío mecánico (M4.2): reemite exclusivamente lo Pendiente o en Error,
    tal cual la última acción pedida — nunca toca lo Confirmado."""
    target = await _resolve_target(node_id, session)
    reader = AdminOperationRemoteFlagStateReader(session)
    plan = await compute_resend_plan(reader, node_id, body.flag_type)
    if not plan.items:
        return RemoteFlagSyncOut(batch_id=None, operation_type=f"{body.flag_type}.resend", node_ids=[], items=0)

    planned = to_planned_operations(plan, target.gateway_id)
    batch = await request.app.state.batches.create_planned(
        name=f"Reenviar pendientes {body.flag_type} remoto: {target.short_name or target.node_id}",
        operation_type=f"{body.flag_type}.resend",
        params={},
        planned=planned,
        scope_description={"remote_flag_resend": body.flag_type, "target_node_id": node_id},
        created_by="admin",
    )
    assert batch.id is not None
    return RemoteFlagSyncOut(
        batch_id=batch.id, operation_type=f"{body.flag_type}.resend", node_ids=batch.node_ids, items=len(plan.items)
    )
