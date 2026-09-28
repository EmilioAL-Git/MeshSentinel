from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from noc.application.stats import StatRecord, StatsSummary

router = APIRouter(prefix="/stats", tags=["stats"])


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
    events_last_24h: int
    records: list[StatRecordOut]

    @classmethod
    def from_entity(cls, s: StatsSummary) -> "StatsSummaryOut":
        return cls(
            generated_at=s.generated_at,
            nodes_total=s.nodes_total,
            nodes_online=s.nodes_online,
            network_age_days=s.network_age_days,
            events_last_24h=s.events_last_24h,
            records=[StatRecordOut.from_entity(r) for r in s.records],
        )


@router.get("/summary", response_model=StatsSummaryOut)
async def stats_summary(request: Request) -> StatsSummaryOut:
    summary = await request.app.state.stats.get_summary()
    return StatsSummaryOut.from_entity(summary)
