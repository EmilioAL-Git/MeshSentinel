from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from noc.adapters.api.schemas import GatewayOut
from noc.application.dashboard import CriticalNode, DashboardSummary, Thresholds

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ThresholdsOut(BaseModel):
    low_battery_percent: int
    offline_minutes_warning: int
    offline_percent_warning: float
    offline_percent_critical: float
    snr_degraded_db: float
    node_offline_after_seconds: int

    @classmethod
    def from_entity(cls, t: Thresholds) -> "ThresholdsOut":
        return cls(**{f: getattr(t, f) for f in cls.model_fields})


class CriticalNodeOut(BaseModel):
    node_id: str
    short_name: str | None
    long_name: str | None
    reasons: list[Literal["low_battery", "inactive", "degraded_snr"]]
    battery_level: int | None
    snr: float | None
    last_seen_at: datetime | None
    online: bool

    @classmethod
    def from_entity(cls, c: CriticalNode) -> "CriticalNodeOut":
        return cls(**{f: getattr(c, f) for f in cls.model_fields})


class DashboardSummaryOut(BaseModel):
    status: Literal["HEALTHY", "WARNING", "CRITICAL"]
    generated_at: datetime
    nodes_total: int
    nodes_online: int
    nodes_offline: int
    offline_percent: float
    gateways_total: int
    gateways_connected: int
    low_battery_count: int
    avg_battery_percent: float | None
    avg_seconds_since_last_seen: float | None
    events_last_hour: int
    critical_nodes: list[CriticalNodeOut]
    gateways: list[GatewayOut]
    thresholds: ThresholdsOut

    @classmethod
    def from_entity(cls, s: DashboardSummary) -> "DashboardSummaryOut":
        assert s.thresholds is not None
        return cls(
            status=s.status,
            generated_at=s.generated_at,
            nodes_total=s.nodes_total,
            nodes_online=s.nodes_online,
            nodes_offline=s.nodes_offline,
            offline_percent=s.offline_percent,
            gateways_total=s.gateways_total,
            gateways_connected=s.gateways_connected,
            low_battery_count=s.low_battery_count,
            avg_battery_percent=s.avg_battery_percent,
            avg_seconds_since_last_seen=s.avg_seconds_since_last_seen,
            events_last_hour=s.events_last_hour,
            critical_nodes=[CriticalNodeOut.from_entity(c) for c in s.critical_nodes],
            gateways=[GatewayOut.from_entity(g) for g in s.gateways],
            thresholds=ThresholdsOut.from_entity(s.thresholds),
        )


@router.get("/summary", response_model=DashboardSummaryOut)
async def dashboard_summary(request: Request) -> DashboardSummaryOut:
    summary = await request.app.state.dashboard.get_summary()
    return DashboardSummaryOut.from_entity(summary)
