"""Despacho de transiciones de alerta a los canales configurados en BD.

El motor no conoce los canales: este notificador es un listener más. Añadir un
canal nuevo (Telegram, email, Discord...) = un adapter registrado en
noc.adapters.notifications.CHANNEL_TYPES; el motor y este módulo no cambian.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.notifications import build_channel
from noc.adapters.persistence.alert_repositories import SqlChannelRepository
from noc.application.alerting.engine import AlertTransition

logger = logging.getLogger("noc.alerts.notify")


class AlertNotifier:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(self, transition: AlertTransition) -> None:
        if transition.kind == "reminder" and transition.alert.status == "acknowledged":
            return  # una alerta reconocida no insiste
        async with self._session_factory() as session:
            channels = await SqlChannelRepository(session).list_enabled()
        for config in channels:
            channel = build_channel(config)
            if channel is None:
                logger.warning("Unknown channel_type=%s (channel=%s)", config.channel_type, config.name)
                continue
            try:
                await channel.send(transition.alert, transition.kind)
            except Exception:
                # Un canal caído nunca detiene el motor ni el resto de canales
                logger.exception("Notification failed channel=%s kind=%s", config.name, transition.kind)
