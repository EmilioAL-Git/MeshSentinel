from noc.adapters.notifications.ntfy import NtfyChannel
from noc.adapters.notifications.webhook import WebhookChannel
from noc.application.alerting.ports import NotificationChannel
from noc.domain.alerts.entities import NotificationChannelConfig

# Registro extensible: añadir un canal = una entrada nueva (ADR 0008/0012)
CHANNEL_TYPES: dict[str, type] = {
    "webhook": WebhookChannel,
    "ntfy": NtfyChannel,
}


def build_channel(config: NotificationChannelConfig) -> NotificationChannel | None:
    cls = CHANNEL_TYPES.get(config.channel_type)
    return cls(config.config) if cls else None
