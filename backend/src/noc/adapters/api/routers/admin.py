from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.admin.registry import OPERATIONS, validate_operation
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


class OperationIn(BaseModel):
    node_id: str = Field(pattern=r"^![0-9a-f]{8}$")
    operation_type: str
    params: dict[str, Any] = {}
    timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    max_attempts: int | None = Field(default=None, ge=1, le=10)


class OperationOut(BaseModel):
    id: int
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
