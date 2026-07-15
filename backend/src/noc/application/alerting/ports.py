from typing import Protocol

from noc.application.alerting.message import NotificationMessage


class NotificationProvider(Protocol):
    """Puerto de proveedor de notificación (ADR 0008, ampliado — ver ADR de
    notificaciones multi-proveedor).

    Las implementaciones viven en noc.adapters.notifications.
    """

    async def send(self, message: NotificationMessage) -> None: ...

    async def test(self) -> None:
        """Envía un mensaje de prueba canned (`message.test_message()`)."""
        ...

    def validate(self) -> list[str]:
        """Errores de configuración (vacía = válida). Síncrona: solo mira la
        forma de `configuration`, no hace I/O de red."""
        ...
