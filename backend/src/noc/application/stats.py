"""Estadísticas curiosas de la malla ("Estadísticas"): récords individuales por
nodo (más air TX, más caliente, más uptime...) sobre datos ya persistidos.

Sin relación con el Dashboard NOC (nada de salud/umbrales/alertas) — es un
panel de datos curiosos para el operador. Misma filosofía ADR 0011: una sola
pasada en memoria sobre lo que ya trae `list_summaries()`, caché TTL en
proceso para no recalcular en cada cliente conectado.

Cada récord del resumen es solo la CABEZA de un ranking completo (todos los
nodos con ese dato, ordenados) — la UI permite desplegarlo ("nodos por
debajo del top"), así que `_compute()` calcula y cachea ambos a la vez sobre
el mismo `NetworkStats` en memoria; nunca se vuelve a consultar la BD para
pedir un ranking dentro de la ventana de caché.

Ventana temporal (`hours`, 1..168 = máximo 1 semana): los récords de telemetría
y altitud son el EXTREMO de las muestras recibidas dentro de la ventana (pico
de air TX, temperatura máxima...), y los de estado actual (SNR, saltos,
pasarelas, antigüedad) solo consideran nodos con actividad en ella.
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
from noc.domain.nodes.entities import NodeSummary

MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168  # 1 semana
DEFAULT_WINDOW_HOURS = 24


def clamp_hours(hours: int) -> int:
    return max(MIN_WINDOW_HOURS, min(MAX_WINDOW_HOURS, hours))


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
    window_hours: int
    events_in_window: int
    records: list[StatRecord] = field(default_factory=list)


@dataclass(slots=True)
class _NetworkStats:
    summary: StatsSummary
    # Ranking completo por clave de récord, ya ordenado (mejor primero) —
    # el récord del resumen es siempre `rankings[key][0]`.
    rankings: dict[str, list[StatRecord]] = field(default_factory=dict)


class StatsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cache: dict[int, tuple[float, _NetworkStats]] = {}
        self._lock = asyncio.Lock()

    async def get_summary(self, hours: int = DEFAULT_WINDOW_HOURS) -> StatsSummary:
        stats = await self._get_stats(clamp_hours(hours))
        return stats.summary

    async def get_ranking(self, key: str, hours: int = DEFAULT_WINDOW_HOURS) -> list[StatRecord] | None:
        """Todos los nodos con dato para `key`, ordenados (mejor primero).
        `None` si `key` no es un récord conocido (404 en el router)."""
        stats = await self._get_stats(clamp_hours(hours))
        return stats.rankings.get(key)

    async def _get_stats(self, hours: int) -> _NetworkStats:
        async with self._lock:
            hit = self._cache.get(hours)
            if hit and (time.monotonic() - hit[0]) < self._settings.stats_cache_seconds:
                return hit[1]
            stats = await self._compute(hours)
            if len(self._cache) >= 32:  # ventanas distintas acotadas (máx. 168 posibles)
                self._cache.clear()
            self._cache[hours] = (time.monotonic(), stats)
            return stats

    async def _compute(self, hours: int) -> _NetworkStats:
        s = self._settings
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)

        async with self._session_factory() as session:
            summaries = await SqlNodeRepository(session).list_summaries()
            telemetry_repo = SqlTelemetryRepository(session)
            device_ext = await telemetry_repo.extremes_since("device", since)
            env_ext = await telemetry_repo.extremes_since("environment", since)
            max_altitude = await SqlPositionRepository(session).max_altitude_since(since)
            links = await SqlNodeGatewayLinkRepository(session).list_all()
            events_in_window = await telemetry_repo.count_since(since) + await SqlPositionRepository(
                session
            ).count_since(since)

        # Los nodos ignorados no cuentan para las estadísticas (mismo criterio
        # que el Dashboard, M1.2): su telemetría sigue persistiéndose igual.
        summaries = [x for x in summaries if not x.node.is_ignored]
        # Nodos con actividad dentro de la ventana: base de los récords de
        # estado actual (SNR, saltos, pasarelas, antigüedad).
        active = [
            x for x in summaries
            if x.node.last_seen_at is not None and ensure_utc(x.node.last_seen_at) >= since
        ]
        active_ids = {x.node.node_id for x in active}

        gateways_by_node: dict[str, set[str]] = {}
        for link in links:
            if link.node_id in active_ids:
                gateways_by_node.setdefault(link.node_id, set()).add(link.gateway_id)

        nodes_total = len(summaries)
        nodes_online = sum(1 for x in summaries if x.node.is_online(s.node_offline_after_seconds, now))
        first_seens = [x.node.first_seen_at for x in summaries if x.node.first_seen_at is not None]
        network_age_days = (now - ensure_utc(min(first_seens))).days if first_seens else None

        records: list[StatRecord] = []
        rankings: dict[str, list[StatRecord]] = {}

        def rank(
            key: str,
            label: str,
            icon: str,
            unit: str | None,
            getter: Callable[[NodeSummary], float | int | None],
            *,
            minimum: bool = False,
            population: list[NodeSummary] | None = None,
        ) -> None:
            entries: list[StatRecord] = []
            for x in summaries if population is None else population:
                v = getter(x)
                if v is None:
                    continue
                entries.append(
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
            if not entries:
                return
            entries.sort(key=lambda r: r.value, reverse=not minimum)
            rankings[key] = entries
            records.append(entries[0])

        def peak(ext: dict[str, dict[str, float | int | None]], field_name: str) -> Callable[[NodeSummary], float | int | None]:
            return lambda x: ext.get(x.node.node_id, {}).get(field_name)

        rank("air_tx", "Más ocupado transmitiendo", "📡", "%", peak(device_ext, "air_util_tx"))
        rank("channel_util", "Canal más saturado", "📶", "%", peak(device_ext, "channel_utilization"))
        rank("uptime", "Más tiempo sin reiniciar", "⏱", "s", peak(device_ext, "uptime_seconds"))
        rank("low_battery", "Batería más baja", "🪫", "%", peak(device_ext, "min_battery"), minimum=True)
        rank("altitude", "El más alto", "⛰", "m", lambda x: max_altitude.get(x.node.node_id))
        rank("best_snr", "Mejor señal", "✦", "dB", lambda x: x.node.snr, population=active)
        rank("worst_snr", "Señal más débil", "〰", "dB", lambda x: x.node.snr, minimum=True, population=active)
        rank("most_hops", "El más lejano (saltos)", "⇢", "saltos", lambda x: x.node.hops_away, population=active)
        rank(
            "veteran", "El veterano", "🕰", "días",
            lambda x: (now - ensure_utc(x.node.first_seen_at)).days if x.node.first_seen_at else None,
            population=active,
        )
        rank(
            "rookie", "El recién llegado", "✨", "min",
            lambda x: (
                (now - ensure_utc(x.node.first_seen_at)).total_seconds() / 60
                if x.node.first_seen_at
                else None
            ),
            minimum=True,
            population=active,
        )
        rank(
            "most_gateways", "Más pasarelas lo oyen", "🛰", "pasarelas",
            lambda x: len(gateways_by_node.get(x.node.node_id, ())) or None,
            population=active,
        )
        rank("hottest", "El más caliente", "🔥", "°C", peak(env_ext, "max_temperature"))
        rank("coldest", "El más frío", "🧊", "°C", peak(env_ext, "min_temperature"), minimum=True)
        rank("humid", "Ambiente más húmedo", "💧", "%", peak(env_ext, "relative_humidity"))
        rank("pressure", "Presión más alta", "⏲", "hPa", peak(env_ext, "pressure"))

        summary = StatsSummary(
            generated_at=now,
            nodes_total=nodes_total,
            nodes_online=nodes_online,
            network_age_days=network_age_days,
            window_hours=hours,
            events_in_window=events_in_window,
            records=records,
        )
        return _NetworkStats(summary=summary, rankings=rankings)
