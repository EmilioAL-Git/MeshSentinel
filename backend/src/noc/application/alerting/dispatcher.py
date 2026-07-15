"""Despacho de transiciones de alerta a los proveedores configurados en BD.

El motor no conoce los proveedores: este dispatcher es un listener más.
Enrutado: si la regla no tiene canales lógicos asignados, se hace broadcast
a TODOS los `notification_providers` enabled=True (comportamiento previo a
la arquitectura multi-proveedor, sin cambios para nadie que no asigne
canales); si SÍ tiene canales, se envía solo a la unión deduplicada de
proveedores de esos canales. Añadir un proveedor nuevo (Telegram, email,
Discord...) = un adapter registrado en noc.adapters.notifications.PROVIDERS;
el motor y este módulo no cambian.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.notifications import build_provider
from noc.adapters.persistence.alert_repositories import (
    SqlAlertRuleRepository,
    SqlNotificationChannelRepository,
    SqlNotificationProviderRepository,
)
from noc.application.alerting.engine import AlertTransition
from noc.application.alerting.message import render_message

logger = logging.getLogger("noc.alerts.notify")


class NotificationDispatcher:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(self, transition: AlertTransition) -> None:
        if transition.kind == "reminder" and transition.alert.status == "acknowledged":
            return  # una alerta reconocida no insiste
        async with self._session_factory() as session:
            rule = await SqlAlertRuleRepository(session).get(transition.alert.rule_id)
            if rule and rule.channel_ids:
                providers = await SqlNotificationChannelRepository(session).list_providers_for_channels(
                    rule.channel_ids
                )
            else:
                providers = await SqlNotificationProviderRepository(session).list_enabled()
        message = render_message(transition.alert, transition.kind)
        for config in providers:
            provider = build_provider(config)
            if provider is None:
                logger.warning("Unknown provider=%s (name=%s)", config.provider, config.name)
                continue
            try:
                await provider.send(message)
            except Exception:
                # Un proveedor caído nunca detiene el motor ni al resto
                logger.exception("Notification failed provider=%s kind=%s", config.name, transition.kind)
