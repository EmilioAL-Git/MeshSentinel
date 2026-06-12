from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.routers.health import ComponentStatus, _check
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.config import get_settings

router = APIRouter(prefix="/system", tags=["system"])


class GatewayHealth(BaseModel):
    gateway_id: str
    status: str
    transport: str
    local_node_id: str | None
    last_heartbeat_at: datetime | None
    stale: bool
    healthy: bool


class SystemHealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: ComponentStatus
    redis: ComponentStatus
    gateways: list[GatewayHealth]


class VersionResponse(BaseModel):
    app: str
    version: str
    git_commit: str
    build_time: str
    environment: str
    events_schema_version: int = 1


def _is_stale(updated_at: datetime | None, threshold_seconds: int) -> bool:
    if updated_at is None:
        return True
    if updated_at.tzinfo is None:  # SQLite devuelve naive; se persiste siempre UTC
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated_at).total_seconds() > threshold_seconds


@router.get("/health", response_model=SystemHealthResponse)
async def system_health(request: Request, session: SessionDep) -> SystemHealthResponse:
    settings = get_settings()
    db = await _check(request.app.state.db.ping())
    redis_ = await _check(request.app.state.event_bus.ping())

    gateways = []
    if db.status == "ok":
        for g in await SqlGatewayRepository(session).list_all():
            stale = _is_stale(g.updated_at, settings.gateway_stale_after_seconds)
            gateways.append(
                GatewayHealth(
                    gateway_id=g.gateway_id,
                    status=g.status,
                    transport=g.transport,
                    local_node_id=g.local_node_id,
                    last_heartbeat_at=g.updated_at,
                    stale=stale,
                    healthy=g.status == "connected" and not stale,
                )
            )

    overall: Literal["ok", "degraded"] = (
        "ok"
        if db.status == "ok" and redis_.status == "ok" and any(g.healthy for g in gateways)
        else "degraded"
    )
    return SystemHealthResponse(status=overall, database=db, redis=redis_, gateways=gateways)


@router.get("/version", response_model=VersionResponse)
async def system_version() -> VersionResponse:
    settings = get_settings()
    return VersionResponse(
        app=settings.app_name,
        version=settings.version,
        git_commit=settings.git_commit,
        build_time=settings.build_time,
        environment=settings.environment,
    )
