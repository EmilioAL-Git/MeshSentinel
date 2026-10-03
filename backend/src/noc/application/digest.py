"""Resumen periódico de la red por las integraciones de notificación.

Cada `digest_period_hours` (0 = desactivado), a la hora UTC `digest_hour_utc`,
se envía a TODAS las integraciones habilitadas un mensaje con el estado de la
red, novedades y alertas de la ventana y unos cuantos récords. Reutiliza los
proveedores de alertas (Telegram/webhook/ntfy): para ellos es un
`NotificationMessage` más con `kind="digest"`.

El instante del último envío se persiste en `system_settings` para que un
reinicio no duplique ni se salte el resumen.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.notifications import build_provider
from noc.adapters.persistence.alert_repositories import SqlNotificationProviderRepository
from noc.adapters.persistence.models import AlertModel, NodeModel
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.alerting.message import NotificationMessage
from noc.application.dashboard import DashboardService, DashboardSummary
from noc.application.stats import StatRecord, StatsService
from noc.config import Settings

logger = logging.getLogger("noc.digest")

LAST_SENT_KEY = "digest.last_sent_at"
CHECK_INTERVAL_SECONDS = 60
# Margen para que un envío a las 08:00:30 no se salte el del día siguiente
DUE_SLACK = timedelta(minutes=10)
MAX_RECORDS = 4

_STATUS_TEXT = {"HEALTHY": "Estable", "WARNING": "Atención", "CRITICAL": "Crítica"}
_STATUS_SEVERITY = {"HEALTHY": "INFO", "WARNING": "WARNING", "CRITICAL": "CRITICAL"}
# Los proveedores (Telegram usa Markdown legado) rompen con estos caracteres
_MD_UNSAFE = re.compile(r"[_*`\[\]]")


def _clean(text: str | None) -> str:
    return _MD_UNSAFE.sub(" ", text or "").strip()


def _window_label(hours: int) -> str:
    if hours % 24 == 0:
        days = hours // 24
        return "24 h" if days == 1 else f"{days} días"
    return f"{hours} h"


def _record_line(r: StatRecord) -> str:
    who = _clean(r.long_name or r.short_name or r.node_id)
    value = f"{r.value:g}" if isinstance(r.value, float) else str(r.value)
    return f"{r.icon} {r.label}: {who} ({value}{' ' + r.unit if r.unit else ''})"


def build_digest_message(
    *,
    dashboard: DashboardSummary,
    records: list[StatRecord],
    new_nodes: int,
    alerts_fired: int,
    alerts_critical: int,
    alerts_active: int,
    hours: int,
    now: datetime,
) -> NotificationMessage:
    lines = [
        f"Red: {_STATUS_TEXT.get(dashboard.status, dashboard.status)} · "
        f"{dashboard.nodes_online}/{dashboard.nodes_total} nodos en línea "
        f"({dashboard.offline_percent:.0f}% offline)",
        f"Pasarelas: {dashboard.gateways_connected}/{dashboard.gateways_total} conectadas",
        f"Nodos nuevos: {new_nodes}",
        f"Alertas: {alerts_fired} disparadas"
        + (f" ({alerts_critical} críticas)" if alerts_critical else "")
        + f" · {alerts_active} activas ahora",
    ]
    if dashboard.low_battery_count:
        lines.append(f"Batería baja: {dashboard.low_battery_count} nodos")
    for record in records[:MAX_RECORDS]:
        lines.append(_record_line(record))
    return NotificationMessage(
        title=f"Resumen de la red · últimas {_window_label(hours)}",
        severity=_STATUS_SEVERITY.get(dashboard.status, "INFO"),  # type: ignore[arg-type]
        kind="digest",
        subject_label="system:meshsentinel",
        body="\n".join(lines),
        occurred_at=now,
    )


def is_due(
    *, now: datetime, period_hours: int, hour_utc: int, last_sent: datetime | None
) -> bool:
    if period_hours <= 0 or now.hour != hour_utc % 24:
        return False
    if last_sent is None:
        return True
    return now - last_sent >= timedelta(hours=period_hours) - DUE_SLACK


class DigestService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        dashboard: DashboardService,
        stats: StatsService,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._dashboard = dashboard
        self._stats = stats
        self._task: asyncio.Task[None] | None = None

    async def _gather(self, hours: int, now: datetime) -> NotificationMessage:
        since = now - timedelta(hours=hours)
        async with self._session_factory() as session:
            new_nodes = (
                await session.execute(
                    select(func.count()).select_from(NodeModel).where(NodeModel.first_seen_at >= since)
                )
            ).scalar_one()
            alerts_fired = (
                await session.execute(
                    select(func.count()).select_from(AlertModel).where(AlertModel.fired_at >= since)
                )
            ).scalar_one()
            alerts_critical = (
                await session.execute(
                    select(func.count())
                    .select_from(AlertModel)
                    .where(AlertModel.fired_at >= since, AlertModel.severity == "CRITICAL")
                )
            ).scalar_one()
            alerts_active = (
                await session.execute(
                    select(func.count())
                    .select_from(AlertModel)
                    .where(AlertModel.status.in_(("firing", "acknowledged")))
                )
            ).scalar_one()
        summary = await self._dashboard.get_summary()
        stats = await self._stats.get_summary(min(168, max(1, hours)))
        return build_digest_message(
            dashboard=summary,
            records=stats.records,
            new_nodes=int(new_nodes),
            alerts_fired=int(alerts_fired),
            alerts_critical=int(alerts_critical),
            alerts_active=int(alerts_active),
            hours=hours,
            now=now,
        )

    async def send_now(self, hours: int | None = None) -> tuple[int, int]:
        """Envía el resumen ya. Devuelve (entregados, integraciones habilitadas)."""
        now = datetime.now(timezone.utc)
        window = hours or (int(self._settings.digest_period_hours) or 24)
        message = await self._gather(window, now)
        async with self._session_factory() as session:
            providers = await SqlNotificationProviderRepository(session).list_enabled()
        delivered = 0
        for config in providers:
            provider = build_provider(config)
            if provider is None:
                continue
            try:
                await provider.send(message)
                delivered += 1
            except Exception:
                logger.exception("Digest failed provider=%s", config.name)
        async with self._session_factory() as session:
            await SqlSystemSettingsRepository(session).upsert(LAST_SENT_KEY, now.isoformat(), None)
            await session.commit()
        return delivered, len(providers)

    async def _last_sent(self) -> datetime | None:
        async with self._session_factory() as session:
            raw = (await SqlSystemSettingsRepository(session).list_all()).get(LAST_SENT_KEY)
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    async def last_sent_at(self) -> datetime | None:
        return await self._last_sent()

    async def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if not is_due(
            now=now,
            period_hours=int(self._settings.digest_period_hours),
            hour_utc=int(self._settings.digest_hour_utc),
            last_sent=await self._last_sent(),
        ):
            return False
        await self.send_now()
        return True

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="digest-loop")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("digest tick failed")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
