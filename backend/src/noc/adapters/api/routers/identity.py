"""Identidad de nodos y seguridad de claves (ADR 0034)."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from noc.adapters.api.deps import RequireManagerDep, SessionDep
from noc.adapters.persistence.identity_merge import merge_identity
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.node_identity import (
    find_duplicate_keys,
    find_weak_keys,
    pair_identity_changes,
)

router = APIRouter(prefix="/identity", tags=["identity"])


class IdentityChangeOut(BaseModel):
    predecessor_id: str
    successor_id: str
    basis: str  # derived_num | same_key
    predecessor_last_seen_at: datetime | None
    successor_first_seen_at: datetime | None
    predecessor_quiet: bool | None


class DuplicateKeyOut(BaseModel):
    key_fingerprint: str
    node_ids: list[str]


class WeakKeyOut(BaseModel):
    node_id: str
    reason: str


class IdentityReportOut(BaseModel):
    changes: list[IdentityChangeOut]
    duplicate_keys: list[DuplicateKeyOut]
    weak_keys: list[WeakKeyOut]


class MergeIn(BaseModel):
    predecessor_id: str
    successor_id: str
    confirm: str  # debe ser el predecessor_id (mismo patrón de confirmación que M1.3)


class MergeOut(BaseModel):
    moved: dict[str, int]


@router.get("", response_model=IdentityReportOut)
async def identity_report(session: SessionDep) -> IdentityReportOut:
    """Cambios de identidad 2.8 detectados + claves duplicadas/débiles.
    Calculado al vuelo sobre la NodeDB (una pasada, sin tabla propia)."""
    nodes = await SqlNodeRepository(session).list_all()
    changes = pair_identity_changes(nodes)
    return IdentityReportOut(
        changes=[IdentityChangeOut(**{f: getattr(c, f) for f in IdentityChangeOut.model_fields}) for c in changes],
        duplicate_keys=[
            DuplicateKeyOut(key_fingerprint=g.key_fingerprint, node_ids=g.node_ids)
            for g in find_duplicate_keys(nodes, changes)
        ],
        weak_keys=[WeakKeyOut(node_id=w.node_id, reason=w.reason) for w in find_weak_keys(nodes)],
    )


@router.post("/merge", response_model=MergeOut)
async def merge(body: MergeIn, session: SessionDep, _user: RequireManagerDep) -> MergeOut:
    """Fusiona el historial del nodo viejo en el nuevo y borra el viejo.
    Solo para pares que el detector avala por clave (nunca a petición libre),
    y exige teclear el id del nodo viejo."""
    if body.confirm != body.predecessor_id:
        raise HTTPException(status_code=400, detail="confirm debe ser el id del nodo viejo")
    nodes = await SqlNodeRepository(session).list_all()
    valid = {(c.predecessor_id, c.successor_id) for c in pair_identity_changes(nodes)}
    if (body.predecessor_id, body.successor_id) not in valid:
        raise HTTPException(
            status_code=409, detail="El par no es un cambio de identidad verificable por clave"
        )
    moved = await merge_identity(session, body.predecessor_id, body.successor_id)
    await session.commit()
    return MergeOut(moved=moved)
