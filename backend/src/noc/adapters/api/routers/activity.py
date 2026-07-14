"""Registro persistente del diario operativo (fase de hardening).

Devuelve envelopes `activity.event` idénticos a los del WebSocket (más un
`log_id` para paginar hacia atrás): el frontend siembra su buffer con el
mismo parser del feed en vivo, sin un segundo formato.
"""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.activity_repositories import SqlActivityLogRepository

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityLogItemOut(BaseModel):
    log_id: int
    schema_version: int
    event_type: str
    event_id: str
    gateway_id: str | None
    timestamp: str
    payload: dict[str, Any]


@router.get("", response_model=list[ActivityLogItemOut])
async def list_activity(
    session: SessionDep,
    limit: int = Query(default=300, ge=1, le=1000),
    before_id: int | None = Query(default=None, ge=1),
    node_id: str | None = None,
    source: str | None = Query(default=None, pattern="^(mesh|gateway|alert|admin|system)$"),
    gateway_id: str | None = Query(default=None, max_length=64),
    group_id: int | None = None,
    q: str | None = Query(default=None, max_length=120),
    internal_type: str | None = Query(default=None, max_length=32),
) -> list[ActivityLogItemOut]:
    items = await SqlActivityLogRepository(session).list_recent(
        limit,
        before_id=before_id,
        node_id=node_id,
        source=source,
        gateway_id=gateway_id,
        group_id=group_id,
        q=q,
        internal_type=internal_type,
    )
    return [ActivityLogItemOut(**item) for item in items]
