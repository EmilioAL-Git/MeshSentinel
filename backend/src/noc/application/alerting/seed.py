"""Siembra de reglas por defecto desde los umbrales del Dashboard: coherencia
Dashboard ⇄ alertas sin duplicar configuración.

Semántica INCREMENTAL por rule_type (motor de reglas §1): se siembra cada
tipo cuyo rule_type no exista aún en BD — así una instalación existente
recibe las reglas nuevas de una versión sin perder los ajustes/altas/bajas
del operador sobre las que ya tenía (el criterio "solo con BD vacía"
anterior habría dejado los tipos nuevos invisibles para siempre). Borrar
una regla sembrada la revive en el próximo arranque; para silenciarla, el
camino es deshabilitarla (enabled=false), no borrarla.
"""

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
        # Motor de reglas §1 (defaults editables en la UI, no vienen de env:
        # a diferencia de los 4 históricos no replican un umbral del Dashboard)
        AlertRule(
            name="Pasarela sin tráfico",
            rule_type="gateway_no_traffic",
            severity="WARNING",
            duration_seconds=1800,
        ),
        AlertRule(
            name="Redundancia baja",
            rule_type="low_redundancy",
            severity="INFO",
            threshold=50,
        ),
        AlertRule(
            name="Temperatura alta",
            rule_type="temperature_high",
            severity="WARNING",
            threshold=45,
        ),
        AlertRule(
            name="Canal saturado",
            rule_type="channel_utilization_high",
            severity="WARNING",
            threshold=25,
        ),
        AlertRule(
            name="Posición perdida",
            rule_type="position_lost",
            severity="INFO",
            duration_seconds=7200,
        ),
        AlertRule(
            name="Enlace de vecinos perdido",
            rule_type="neighbor_link_lost",
            severity="INFO",
            duration_seconds=7200,
        ),
    ]


async def seed_default_rules(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session, session.begin():
        repo = SqlAlertRuleRepository(session)
        existing_types = {r.rule_type for r in await repo.list_all()}
        seeded = 0
        for rule in default_rules(settings):
            if rule.rule_type in existing_types:
                continue
            await repo.create(rule)
            seeded += 1
        if seeded:
            logger.info("Seeded %d default alert rules", seeded)
