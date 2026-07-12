"""API del Batch Engine (M2).

- POST /admin/batches/preview  — simulación sin efectos
- POST /admin/batches          — crea el lote (alcance = node_ids congelados)
- GET  /admin/batches          — historial con filtros
- GET  /admin/batches/{id}     — detalle + progreso
- GET  /admin/batches/{id}/operations — operaciones por nodo
- POST /admin/batches/{id}/pause|resume|cancel
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.routers.admin_operations import OperationOut
from noc.adapters.api.schemas import GatewaySelectionIn
from noc.adapters.persistence.admin_repositories import (
    SqlAdminBatchRepository,
    SqlAdminOperationRepository,
)
from noc.application.admin.batches import BatchScope
from noc.application.node_filters import NodeFilters
from noc.domain.admin.entities import AdminBatch

router = APIRouter(prefix="/admin/batches", tags=["admin-batches"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class ScopeIn(BaseModel):
    node_ids: list[str] = Field(default_factory=list)
    q: str | None = None
    hw_model: str | None = None
    tag: str | None = None
    group_id: int | None = None
    favorite: bool | None = None
    online: bool | None = None
    battery_below: int | None = None
    gateway_id: str | None = None
    include_ignored: bool = False

    def to_scope(self) -> BatchScope:
        filters = NodeFilters(
            q=self.q,
            hw_model=self.hw_model,
            tag=self.tag,
            group_id=self.group_id,
            favorite=self.favorite,
            online=self.online,
            battery_below=self.battery_below,
            gateway_id=self.gateway_id,
            include_ignored=self.include_ignored,
        )
        return BatchScope(
            node_ids=self.node_ids, filters=None if filters.is_empty else filters
        )


class PreviewIn(BaseModel):
    operation_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    scope: ScopeIn


class NodePreviewOut(BaseModel):
    node_id: str
    display_name: str
    eligible: bool
    warnings: list[str]
    blockers: list[str]


class PreviewOut(BaseModel):
    operation_type: str
    params: dict[str, Any]
    total_selected: int
    eligible_count: int
    excluded_count: int
    eligible: list[NodePreviewOut]
    excluded: list[NodePreviewOut]
    requires_verification: bool
    estimated_seconds: int
    scope_description: dict[str, Any]


class BatchCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    operation_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    node_ids: list[str] = Field(min_length=1)
    scope_description: dict[str, Any] | None = None
    gateway_selection: GatewaySelectionIn = Field(default_factory=GatewaySelectionIn)


class BatchOut(BaseModel):
    id: int
    name: str
    operation_type: str
    params: dict[str, Any]
    node_count: int
    status: Literal["running", "paused", "cancelled", "completed", "completed_with_errors"]
    created_by: str
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_entity(cls, b: AdminBatch) -> "BatchOut":
        return cls(
            id=b.id or 0,
            name=b.name,
            operation_type=b.operation_type,
            params=b.params,
            node_count=len(b.node_ids),
            status=b.status,
            created_by=b.created_by,
            created_at=b.created_at,
            started_at=b.started_at,
            finished_at=b.finished_at,
        )


class BatchProgressOut(BaseModel):
    counts: dict[str, int]
    total: int
    done: int
    percent: float
    current_node_id: str | None
    rate_per_minute: float | None
    eta_seconds: int
    elapsed_seconds: int


class BatchDetailOut(BatchOut):
    node_ids: list[str]
    scope_description: dict[str, Any] | None
    progress: BatchProgressOut


def _service(request: Request):
    return request.app.state.batches


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/preview", response_model=PreviewOut)
async def preview_batch(body: PreviewIn, request: Request) -> PreviewOut:
    try:
        preview = await _service(request).preview(body.operation_type, body.params, body.scope.to_scope())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreviewOut(
        operation_type=preview.operation_type,
        params=preview.params,
        total_selected=preview.total_selected,
        eligible_count=len(preview.eligible),
        excluded_count=len(preview.excluded),
        # OJO: NodePreview usa slots=True (sin __dict__) — siempre asdict
        eligible=[NodePreviewOut(**asdict(n)) for n in preview.eligible],
        excluded=[NodePreviewOut(**asdict(n)) for n in preview.excluded],
        requires_verification=preview.requires_verification,
        estimated_seconds=preview.estimated_seconds,
        scope_description=preview.scope_description,
    )


@router.post("", response_model=BatchOut, status_code=201)
async def create_batch(body: BatchCreateIn, request: Request) -> BatchOut:
    try:
        batch = await _service(request).create(
            name=body.name,
            operation_type=body.operation_type,
            params=body.params,
            node_ids=body.node_ids,
            scope_description=body.scope_description,
            forced_gateway_id=body.gateway_selection.gateway_id if body.gateway_selection.mode == "forced" else None,
            use_preference=body.gateway_selection.mode != "auto",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BatchOut.from_entity(batch)


@router.get("", response_model=list[BatchOut])
async def list_batches(
    session: SessionDep,
    status: str | None = None,
    operation_type: str | None = None,
    created_by: str | None = None,
    node_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[BatchOut]:
    batches = await SqlAdminBatchRepository(session).list_batches(
        status=status,
        operation_type=operation_type,
        created_by=created_by,
        node_id=node_id,
        since=since,
        until=until,
        limit=limit,
    )
    return [BatchOut.from_entity(b) for b in batches]


@router.get("/{batch_id}", response_model=BatchDetailOut)
async def get_batch(batch_id: int, request: Request, session: SessionDep) -> BatchDetailOut:
    batch = await SqlAdminBatchRepository(session).get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    progress = await _service(request).progress(session, batch)
    return BatchDetailOut(
        **BatchOut.from_entity(batch).model_dump(),
        node_ids=batch.node_ids,
        scope_description=batch.scope_description,
        progress=BatchProgressOut(**progress),
    )


@router.get("/{batch_id}/operations", response_model=list[OperationOut])
async def batch_operations(
    batch_id: int,
    session: SessionDep,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[OperationOut]:
    if await SqlAdminBatchRepository(session).get(batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    ops = await SqlAdminOperationRepository(session).list_operations(
        status, None, limit, batch_id=batch_id
    )
    return [OperationOut.from_entity(o) for o in ops]


@router.post("/{batch_id}/pause", response_model=BatchOut)
async def pause_batch(batch_id: int, request: Request) -> BatchOut:
    batch = await _service(request).pause(batch_id)
    if batch is None:
        raise HTTPException(status_code=409, detail="Batch not found or not running")
    return BatchOut.from_entity(batch)


@router.post("/{batch_id}/resume", response_model=BatchOut)
async def resume_batch(batch_id: int, request: Request) -> BatchOut:
    batch = await _service(request).resume(batch_id)
    if batch is None:
        raise HTTPException(status_code=409, detail="Batch not found or not paused")
    return BatchOut.from_entity(batch)


@router.post("/{batch_id}/cancel", response_model=BatchOut)
async def cancel_batch(batch_id: int, request: Request) -> BatchOut:
    batch = await _service(request).cancel(batch_id)
    if batch is None:
        raise HTTPException(status_code=409, detail="Batch not found or already terminal")
    return BatchOut.from_entity(batch)
