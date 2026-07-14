"""API de perfiles de configuración (M3).

- CRUD de perfiles + versiones inmutables (editar = nueva versión)
- GET  /admin/profiles/{id}/compare/{node_id}   — diff perfil ↔ nodo
- POST /admin/profiles/{id}/sync/preview        — simulación sin efectos
- POST /admin/profiles/{id}/sync                — crea el lote (Batch Engine)
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from noc.adapters.api.deps import RequireAuthDep, SessionDep
from noc.adapters.api.routers.admin_batches import BatchOut
from noc.adapters.persistence.profile_repositories import SqlConfigProfileRepository
from noc.application.auth.actor import ActorContext
from noc.domain.admin.entities import ConfigProfile, ConfigProfileVersion

router = APIRouter(prefix="/admin/profiles", tags=["admin-profiles"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class ProfileCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    sections: dict[str, dict[str, Any]]


class ProfilePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class VersionCreateIn(BaseModel):
    sections: dict[str, dict[str, Any]]
    comment: str | None = Field(default=None, max_length=256)


class ProfileVersionOut(BaseModel):
    id: int
    profile_id: int
    version: int
    sections: dict[str, dict[str, Any]]
    comment: str | None
    created_by: str
    created_at: datetime | None

    @classmethod
    def from_entity(cls, v: ConfigProfileVersion) -> "ProfileVersionOut":
        return cls(**asdict(v))


class ProfileOut(BaseModel):
    id: int
    name: str
    description: str | None
    latest_version: int
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, p: ConfigProfile) -> "ProfileOut":
        return cls(**asdict(p))


class ProfileDetailOut(ProfileOut):
    sections: dict[str, dict[str, Any]]  # contenido de la última versión


class FieldDiffOut(BaseModel):
    field: str
    kind: str
    profile_value: Any
    node_value: Any
    status: str  # equal | different | unknown


class SectionDiffOut(BaseModel):
    section: str
    risk: str
    has_snapshot: bool
    last_read_at: datetime | None
    fields: list[FieldDiffOut]


class CompareOut(BaseModel):
    profile_id: int
    version: int
    node_id: str
    sections: list[SectionDiffOut]
    equal_count: int
    different_count: int
    unknown_count: int


class SyncIn(BaseModel):
    node_ids: list[str] = Field(min_length=1)
    version: int | None = None
    include_unknown: bool = False
    name: str | None = Field(default=None, max_length=128)


class NodeSyncPlanOut(BaseModel):
    node_id: str
    display_name: str
    eligible: bool
    sections_to_apply: dict[str, dict[str, Any]]
    change_count: int
    equal_count: int
    unknown_sections: list[str]
    warnings: list[str]
    blockers: list[str]


class SyncPreviewOut(BaseModel):
    profile_id: int
    profile_name: str
    version: int
    include_unknown: bool
    eligible: list[NodeSyncPlanOut]
    excluded: list[NodeSyncPlanOut]
    total_operations: int
    estimated_seconds: int


def _service(request: Request):
    return request.app.state.profiles


def _plan_out(plan) -> NodeSyncPlanOut:
    # OJO: NodeSyncPlan usa slots=True (sin __dict__) — siempre asdict
    return NodeSyncPlanOut(**asdict(plan))


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProfileOut])
async def list_profiles(session: SessionDep) -> list[ProfileOut]:
    profiles = await SqlConfigProfileRepository(session).list_profiles()
    return [ProfileOut.from_entity(p) for p in profiles]


@router.post("", response_model=ProfileDetailOut, status_code=201)
async def create_profile(body: ProfileCreateIn, request: Request) -> ProfileDetailOut:
    try:
        profile, version = await _service(request).create(
            body.name, body.description, body.sections
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProfileDetailOut(**asdict(profile), sections=version.sections)


@router.get("/{profile_id}", response_model=ProfileDetailOut)
async def get_profile(profile_id: int, session: SessionDep) -> ProfileDetailOut:
    repo = SqlConfigProfileRepository(session)
    profile = await repo.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    version = await repo.get_version(profile_id, profile.latest_version)
    return ProfileDetailOut(**asdict(profile), sections=version.sections if version else {})


@router.patch("/{profile_id}", response_model=ProfileOut)
async def patch_profile(profile_id: int, body: ProfilePatchIn, session: SessionDep) -> ProfileOut:
    repo = SqlConfigProfileRepository(session)
    changes: dict[str, Any] = {}
    if body.name is not None:
        existing = await repo.get_by_name(body.name)
        if existing is not None and existing.id != profile_id:
            raise HTTPException(status_code=422, detail=f"Ya existe un perfil llamado '{body.name}'")
        changes["name"] = body.name
    if body.description is not None:
        changes["description"] = body.description
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    profile = await repo.update_fields(profile_id, changes)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    await session.commit()
    return ProfileOut.from_entity(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: int, session: SessionDep) -> None:
    if not await SqlConfigProfileRepository(session).delete(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    await session.commit()


# ── Versiones ────────────────────────────────────────────────────────────────


@router.get("/{profile_id}/versions", response_model=list[ProfileVersionOut])
async def list_versions(profile_id: int, session: SessionDep) -> list[ProfileVersionOut]:
    repo = SqlConfigProfileRepository(session)
    if await repo.get(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return [ProfileVersionOut.from_entity(v) for v in await repo.list_versions(profile_id)]


@router.get("/{profile_id}/versions/{version}", response_model=ProfileVersionOut)
async def get_version(profile_id: int, version: int, session: SessionDep) -> ProfileVersionOut:
    v = await SqlConfigProfileRepository(session).get_version(profile_id, version)
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return ProfileVersionOut.from_entity(v)


@router.post("/{profile_id}/versions", response_model=ProfileVersionOut, status_code=201)
async def create_version(
    profile_id: int, body: VersionCreateIn, request: Request
) -> ProfileVersionOut:
    try:
        version = await _service(request).add_version(profile_id, body.sections, body.comment)
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return ProfileVersionOut.from_entity(version)


# ── Comparación y sincronización ─────────────────────────────────────────────


@router.get("/{profile_id}/compare/{node_id}", response_model=CompareOut)
async def compare_profile(
    profile_id: int,
    node_id: str,
    request: Request,
    version: int | None = Query(default=None),
) -> CompareOut:
    try:
        v, diffs = await _service(request).compare(profile_id, node_id, version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sections = [SectionDiffOut(**asdict(d)) for d in diffs]
    all_fields = [f for d in sections for f in d.fields]
    return CompareOut(
        profile_id=profile_id,
        version=v.version,
        node_id=node_id,
        sections=sections,
        equal_count=sum(1 for f in all_fields if f.status == "equal"),
        different_count=sum(1 for f in all_fields if f.status == "different"),
        unknown_count=sum(1 for f in all_fields if f.status == "unknown"),
    )


@router.post("/{profile_id}/sync/preview", response_model=SyncPreviewOut)
async def sync_preview(profile_id: int, body: SyncIn, request: Request) -> SyncPreviewOut:
    try:
        preview = await _service(request).sync_preview(
            profile_id, body.node_ids, body.version, body.include_unknown
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return SyncPreviewOut(
        profile_id=preview.profile_id,
        profile_name=preview.profile_name,
        version=preview.version,
        include_unknown=preview.include_unknown,
        eligible=[_plan_out(p) for p in preview.eligible],
        excluded=[_plan_out(p) for p in preview.excluded],
        total_operations=preview.total_operations,
        estimated_seconds=preview.estimated_seconds,
    )


@router.post("/{profile_id}/sync", response_model=BatchOut, status_code=201)
async def sync_profile(
    profile_id: int, body: SyncIn, request: Request, current_user: RequireAuthDep
) -> BatchOut:
    try:
        batch = await _service(request).sync(
            profile_id,
            body.node_ids,
            version=body.version,
            include_unknown=body.include_unknown,
            name=body.name,
            actor=ActorContext.for_user(current_user),
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return BatchOut.from_entity(batch)
