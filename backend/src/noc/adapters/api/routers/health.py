from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class ComponentStatus(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: ComponentStatus
    redis: ComponentStatus


async def _check(awaitable) -> ComponentStatus:  # type: ignore[no-untyped-def]
    try:
        await awaitable
        return ComponentStatus(status="ok")
    except Exception as exc:  # noqa: BLE001 - health debe reportar, no propagar
        return ComponentStatus(status="error", detail=str(exc))


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    db = await _check(request.app.state.db.ping())
    redis_ = await _check(request.app.state.event_bus.ping())
    overall = "ok" if db.status == "ok" and redis_.status == "ok" else "degraded"
    return HealthResponse(status=overall, database=db, redis=redis_)
