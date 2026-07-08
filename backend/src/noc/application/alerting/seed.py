"""Siembra de reglas por defecto desde los umbrales del Dashboard: coherencia
Dashboard ⇄ alertas sin duplicar configuración. Solo si no existe ninguna regla."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.alert_repositories import SqlAlertRuleRepository
from noc.config import Settings
from noc.domain.alerts.entities import AlertRule

logger = logging.getLogger("noc.alerts")


def default_rules(settings: Settings) -> list[AlertRule]:
    return [
        AlertRule(
            name="Batería baja",
            rule_type="low_battery",
            severity="WARNING",
            threshold=settings.low_battery_threshold,
        ),
        AlertRule(
            name="Nodo sin actividad",
            rule_type="node_offline",
            severity="WARNING",
            duration_seconds=settings.offline_minutes_warning * 60,
        ),
        AlertRule(
            name="SNR degradado",
            rule_type="snr_degraded",
            severity="INFO",
            threshold=settings.snr_degraded_threshold,
        ),
        AlertRule(
            name="Pasarela desconectada",
            rule_type="gateway_disconnected",
            severity="CRITICAL",
            duration_seconds=settings.gateway_stale_after_seconds,
        ),
    ]


async def seed_default_rules(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session, session.begin():
        repo = SqlAlertRuleRepository(session)
        if await repo.count() > 0:
            return
        for rule in default_rules(settings):
            await repo.create(rule)
        logger.info("Seeded %d default alert rules", len(default_rules(settings)))
