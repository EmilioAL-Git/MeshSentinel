from typing import Protocol

from noc.domain.alerts.entities import Alert


class NotificationChannel(Protocol):
    """Puerto de canal de notificación (ADR 0008).

    kind: "fired" | "resolved" | "reminder" | "test".
    Las implementaciones viven en noc.adapters.notifications.
    """

    async def send(self, alert: Alert, kind: str) -> None: ...
