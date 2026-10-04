from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from noc.application.stats import (
    DEFAULT_WINDOW_HOURS,
    MAX_WINDOW_HOURS,
    MIN_WINDOW_HOURS,
    StatRecord,
    StatsSummary,
)

router = APIRouter(prefix="/stats", tags=["stats"])

# Ventana del Top: de 1 hora a 1 semana (168 h).
WindowHours = Annotated[int, Query(ge=MIN_WINDOW_HOURS, le=MAX_WINDOW_HOURS)]


class StatRecordOut(BaseModel):
    key: str
    label: str
    icon: str
    unit: str | None
    node_id: str
    short_name: str | None
    long_name: str | None
    value: float | int

    @classmethod
    def from_entity(cls, r: StatRecord) -> "StatRecordOut":
        return cls(**{f: getattr(r, f) for f in cls.model_fields})


class StatsSummaryOut(BaseModel):
    generated_at: datetime
    nodes_total: int
    nodes_online: int
    network_age_days: int | None
    window_hours: int
    events_in_window: int
    records: list[StatRecordOut]

    @classmethod
    def from_entity(cls, s: StatsSummary) -> "StatsSummaryOut":
        return cls(
            generated_at=s.generated_at,
            nodes_total=s.nodes_total,
            nodes_online=s.nodes_online,
            network_age_days=s.network_age_days,
            window_hours=s.window_hours,
            events_in_window=s.events_in_window,
            records=[StatRecordOut.from_entity(r) for r in s.records],
        )


@router.get("/summary", response_model=StatsSummaryOut)
async def stats_summary(
    request: Request, hours: WindowHours = DEFAULT_WINDOW_HOURS, group_id: int | None = Query(None)
) -> StatsSummaryOut:
    summary = await request.app.state.stats.get_summary(hours, group_id)
    return StatsSummaryOut.from_entity(summary)


@router.get("/ranking/{key}", response_model=list[StatRecordOut])
async def stats_ranking(
    key: str,
    request: Request,
    hours: WindowHours = DEFAULT_WINDOW_HOURS,
    group_id: int | None = Query(None),
) -> list[StatRecordOut]:
    """Todos los nodos con dato para el récord `key`, ordenados (mejor
    primero) — "nodos por debajo del top" al desplegar una tarjeta."""
    ranking = await request.app.state.stats.get_ranking(key, hours, group_id)
    if ranking is None:
        raise HTTPException(status_code=404, detail="Récord desconocido")
    return [StatRecordOut.from_entity(r) for r in ranking]
