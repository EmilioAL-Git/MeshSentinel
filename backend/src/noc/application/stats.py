"""Estadísticas curiosas de la malla ("Estadísticas"): récords individuales por
nodo (más air TX, más caliente, más uptime...) sobre datos ya persistidos.

Sin relación con el Dashboard NOC (nada de salud/umbrales/alertas) — es un
panel de datos curiosos para el operador. Misma filosofía ADR 0011: una sola
pasada en memoria sobre lo que ya trae `list_summaries()`, caché TTL en
proceso para no recalcular en cada cliente conectado.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.repositories import (
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.application.dashboard import ensure_utc
from noc.config import Settings
from noc.domain.nodes.entities import NodeSummary, Telemetry

EXTERNAL_POWER = 101


@dataclass(slots=True)
class StatRecord:
    key: str
    label: str
    icon: str
    unit: str | None
    node_id: str
    short_name: str | None
    long_name: str | None
    value: float | int


@dataclass(slots=True)
class StatsSummary:
    generated_at: datetime
    nodes_total: int
    nodes_online: int
    network_age_days: int | None
    events_last_24h: int
    records: list[StatRecord] = field(default_factory=list)


def _low_battery_value(x: NodeSummary) -> int | None:
    t = x.last_device_telemetry
    if t is None or t.battery_level is None or t.battery_level >= EXTERNAL_POWER:
        return None
    return t.battery_level


class StatsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cache: StatsSummary | None = None
        self._cache_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_summary(self) -> StatsSummary:
        async with self._lock:
            if self._cache and (time.monotonic() - self._cache_at) < self._settings.stats_cache_seconds:
                return self._cache
            summary = await self._compute()
            self._cache, self._cache_at = summary, time.monotonic()
            return summary

    async def _compute(self) -> StatsSummary:
        s = self._settings
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)

        async with self._session_factory() as session:
            summaries = await SqlNodeRepository(session).list_summaries()
            env_telemetry = await SqlTelemetryRepository(session).latest_per_node("environment")
            links = await SqlNodeGatewayLinkRepository(session).list_all()
            events_last_24h = (
                await SqlTelemetryRepository(session).count_since(day_ago)
                + await SqlPositionRepository(session).count_since(day_ago)
            )

        # Los nodos ignorados no cuentan para las estadísticas (mismo criterio
        # que el Dashboard, M1.2): su telemetría sigue persistiéndose igual.
        summaries = [x for x in summaries if not x.node.is_ignored]
        by_id = {x.node.node_id: x for x in summaries}
        env_by_node = {t.node_id: t for t in env_telemetry if t.node_id in by_id}

        gateways_by_node: dict[str, set[str]] = {}
        for link in links:
            if link.node_id in by_id:
                gateways_by_node.setdefault(link.node_id, set()).add(link.gateway_id)

        nodes_total = len(summaries)
        nodes_online = sum(1 for x in summaries if x.node.is_online(s.node_offline_after_seconds, now))
        first_seens = [x.node.first_seen_at for x in summaries if x.node.first_seen_at is not None]
        network_age_days = (now - ensure_utc(min(first_seens))).days if first_seens else None

        records: list[StatRecord] = []

        def top(
            key: str,
            label: str,
            icon: str,
            unit: str | None,
            getter: Callable[[NodeSummary], float | int | None],
            *,
            minimum: bool = False,
        ) -> None:
            best: tuple[NodeSummary, float | int] | None = None
            for x in summaries:
                v = getter(x)
                if v is None:
                    continue
                if best is None or (v < best[1] if minimum else v > best[1]):
                    best = (x, v)
            if best is None:
                return
            x, v = best
            records.append(
                StatRecord(
                    key=key,
                    label=label,
                    icon=icon,
                    unit=unit,
                    node_id=x.node.node_id,
                    short_name=x.node.short_name,
                    long_name=x.node.long_name,
                    value=round(v, 1) if isinstance(v, float) else v,
                )
            )

        top(
            "air_tx", "Más ocupado transmitiendo", "📡", "%",
            lambda x: x.last_device_telemetry.air_util_tx if x.last_device_telemetry else None,
        )
        top(
            "channel_util", "Canal más saturado", "📶", "%",
            lambda x: x.last_device_telemetry.channel_utilization if x.last_device_telemetry else None,
        )
        top(
            "uptime", "Más tiempo sin reiniciar", "⏱", "s",
            lambda x: x.last_device_telemetry.uptime_seconds if x.last_device_telemetry else None,
        )
        top("low_battery", "Batería más baja", "🪫", "%", _low_battery_value, minimum=True)
        top(
            "altitude", "El más alto", "⛰", "m",
            lambda x: x.last_position.altitude_m if x.last_position else None,
        )
        top("best_snr", "Mejor señal", "✦", "dB", lambda x: x.node.snr)
        top("worst_snr", "Señal más débil", "〰", "dB", lambda x: x.node.snr, minimum=True)
        top("most_hops", "El más lejano (saltos)", "⇢", "saltos", lambda x: x.node.hops_away)
        top(
            "veteran", "El veterano", "🕰", "días",
            lambda x: (now - ensure_utc(x.node.first_seen_at)).days if x.node.first_seen_at else None,
        )
        top(
            "rookie", "El recién llegado", "✨", "min",
            lambda x: (
                (now - ensure_utc(x.node.first_seen_at)).total_seconds() / 60
                if x.node.first_seen_at
                else None
            ),
            minimum=True,
        )
        top(
            "most_gateways", "Más pasarelas lo oyen", "🛰", "pasarelas",
            lambda x: len(gateways_by_node.get(x.node.node_id, ())) or None,
        )

        def top_env(
            key: str,
            label: str,
            icon: str,
            unit: str,
            field_name: str,
            *,
            minimum: bool = False,
        ) -> None:
            def getter(x: NodeSummary) -> float | None:
                t: Telemetry | None = env_by_node.get(x.node.node_id)
                return getattr(t, field_name) if t is not None else None

            top(key, label, icon, unit, getter, minimum=minimum)

        top_env("hottest", "El más caliente", "🔥", "°C", "temperature_c")
        top_env("coldest", "El más frío", "🧊", "°C", "temperature_c", minimum=True)
        top_env("humid", "Ambiente más húmedo", "💧", "%", "relative_humidity")
        top_env("pressure", "Presión más alta", "⏲", "hPa", "barometric_pressure_hpa")

        return StatsSummary(
            generated_at=now,
            nodes_total=nodes_total,
            nodes_online=nodes_online,
            network_age_days=network_age_days,
            events_last_24h=events_last_24h,
            records=records,
        )
