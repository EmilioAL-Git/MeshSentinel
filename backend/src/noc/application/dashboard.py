"""Agregación del Dashboard NOC (ADR 0011).

Una sola pasada en memoria sobre los resúmenes de nodos (SQL ya optimizado con
funciones de ventana) + dos COUNT acotados por índice. Caché TTL en proceso para
que N clientes simultáneos no multipliquen el cómputo. compute_status es una
función pura para poder testear las reglas HEALTHY/WARNING/CRITICAL aisladas.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.config import Settings
from noc.domain.nodes.entities import GatewayInfo, NodeSummary

NetworkStatus = Literal["HEALTHY", "WARNING", "CRITICAL"]

EXTERNAL_POWER = 101


def ensure_utc(dt: datetime) -> datetime:
    # SQLite devuelve naive; el sistema persiste siempre UTC
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def is_stale(updated_at: datetime | None, threshold_seconds: int, now: datetime | None = None) -> bool:
    if updated_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - ensure_utc(updated_at)).total_seconds() > threshold_seconds


@dataclass(slots=True)
class CriticalNode:
    node_id: str
    short_name: str | None
    long_name: str | None
    reasons: list[str]
    battery_level: int | None
    snr: float | None
    last_seen_at: datetime | None
    online: bool


@dataclass(slots=True)
class Thresholds:
    low_battery_percent: int
    offline_minutes_warning: int
    offline_percent_warning: float
    offline_percent_critical: float
    snr_degraded_db: float
    node_offline_after_seconds: int


@dataclass(slots=True)
class DashboardSummary:
    status: NetworkStatus
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
    critical_nodes: list[CriticalNode] = field(default_factory=list)
    gateways: list[GatewayInfo] = field(default_factory=list)
    thresholds: Thresholds | None = None


def compute_status(
    *,
    nodes_total: int,
    offline_percent: float,
    gateways_total: int,
    gateways_healthy: int,
    low_battery_count: int,
    events_last_hour: int,
    offline_percent_warning: float,
    offline_percent_critical: float,
) -> NetworkStatus:
    if gateways_total > 0 and gateways_healthy == 0:
        return "CRITICAL"
    if nodes_total > 0 and offline_percent > offline_percent_critical:
        return "CRITICAL"
    if nodes_total > 0 and events_last_hour == 0:
        return "CRITICAL"  # ausencia prolongada de tráfico
    if gateways_total == 0 or nodes_total == 0:
        return "WARNING"  # red aún sin datos: no se puede afirmar salud
    if gateways_healthy < gateways_total:
        return "WARNING"
    if offline_percent >= offline_percent_warning:
        return "WARNING"
    if low_battery_count > 0:
        return "WARNING"
    return "HEALTHY"


class DashboardService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cache: DashboardSummary | None = None
        self._cache_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_summary(self) -> DashboardSummary:
        async with self._lock:
            if self._cache and (time.monotonic() - self._cache_at) < self._settings.dashboard_cache_seconds:
                return self._cache
            summary = await self._compute()
            self._cache, self._cache_at = summary, time.monotonic()
            return summary

    async def _compute(self) -> DashboardSummary:
        s = self._settings
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)

        async with self._session_factory() as session:
            summaries = await SqlNodeRepository(session).list_summaries()
            gateways = await SqlGatewayRepository(session).list_all()
            events_last_hour = (
                await SqlTelemetryRepository(session).count_since(hour_ago)
                + await SqlPositionRepository(session).count_since(hour_ago)
            )

        nodes_total = len(summaries)
        online = [x for x in summaries if x.node.is_online(s.node_offline_after_seconds, now)]
        offline_percent = 100.0 * (nodes_total - len(online)) / nodes_total if nodes_total else 0.0

        batteries = [
            t.battery_level
            for x in summaries
            if (t := x.last_device_telemetry) and t.battery_level is not None and t.battery_level < EXTERNAL_POWER
        ]
        low_battery = [
            x
            for x in summaries
            if (t := x.last_device_telemetry)
            and t.battery_level is not None
            and t.battery_level < s.low_battery_threshold
        ]
        seen_ages = [
            (now - ensure_utc(x.node.last_seen_at)).total_seconds()
            for x in summaries
            if x.node.last_seen_at is not None
        ]

        gateways_healthy = sum(
            1 for g in gateways if g.status == "connected" and not is_stale(g.updated_at, s.gateway_stale_after_seconds, now)
        )

        status = compute_status(
            nodes_total=nodes_total,
            offline_percent=offline_percent,
            gateways_total=len(gateways),
            gateways_healthy=gateways_healthy,
            low_battery_count=len(low_battery),
            events_last_hour=events_last_hour,
            offline_percent_warning=s.offline_percent_warning,
            offline_percent_critical=s.offline_percent_critical,
        )

        return DashboardSummary(
            status=status,
            generated_at=now,
            nodes_total=nodes_total,
            nodes_online=len(online),
            nodes_offline=nodes_total - len(online),
            offline_percent=round(offline_percent, 1),
            gateways_total=len(gateways),
            gateways_connected=gateways_healthy,
            low_battery_count=len(low_battery),
            avg_battery_percent=round(sum(batteries) / len(batteries), 1) if batteries else None,
            avg_seconds_since_last_seen=round(sum(seen_ages) / len(seen_ages), 1) if seen_ages else None,
            events_last_hour=events_last_hour,
            critical_nodes=self._critical_nodes(summaries, now),
            gateways=gateways,
            thresholds=Thresholds(
                low_battery_percent=s.low_battery_threshold,
                offline_minutes_warning=s.offline_minutes_warning,
                offline_percent_warning=s.offline_percent_warning,
                offline_percent_critical=s.offline_percent_critical,
                snr_degraded_db=s.snr_degraded_threshold,
                node_offline_after_seconds=s.node_offline_after_seconds,
            ),
        )

    def _critical_nodes(self, summaries: list[NodeSummary], now: datetime) -> list[CriticalNode]:
        s = self._settings
        result: list[CriticalNode] = []
        for x in summaries:
            node, tel = x.node, x.last_device_telemetry
            reasons: list[str] = []
            battery = tel.battery_level if tel else None
            if battery is not None and battery < s.low_battery_threshold:
                reasons.append("low_battery")
            if node.last_seen_at is not None:
                inactive_s = (now - ensure_utc(node.last_seen_at)).total_seconds()
                if inactive_s > s.offline_minutes_warning * 60:
                    reasons.append("inactive")
            if node.snr is not None and node.snr < s.snr_degraded_threshold:
                reasons.append("degraded_snr")
            if reasons:
                result.append(
                    CriticalNode(
                        node_id=node.node_id,
                        short_name=node.short_name,
                        long_name=node.long_name,
                        reasons=reasons,
                        battery_level=battery,
                        snr=node.snr,
                        last_seen_at=node.last_seen_at,
                        online=node.is_online(s.node_offline_after_seconds, now),
                    )
                )
        # Prioridad: más motivos primero; a igualdad, batería más baja
        result.sort(key=lambda c: (-len(c.reasons), c.battery_level if c.battery_level is not None else 999))
        return result
