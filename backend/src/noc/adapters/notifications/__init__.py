from noc.adapters.notifications.ntfy import NtfyProvider
from noc.adapters.notifications.telegram import TelegramProvider
from noc.adapters.notifications.webhook import WebhookProvider
from noc.application.alerting.ports import NotificationProvider
from noc.domain.alerts.entities import NotificationProviderConfig

# Registro extensible: añadir un proveedor = una entrada nueva (ADR 0008/0012,
# ampliado por la arquitectura multi-proveedor).
PROVIDERS: dict[str, type] = {
    "webhook": WebhookProvider,
    "ntfy": NtfyProvider,
    "telegram": TelegramProvider,
}


def build_provider(config: NotificationProviderConfig) -> NotificationProvider | None:
    cls = PROVIDERS.get(config.provider)
    return cls(config.configuration) if cls else None
