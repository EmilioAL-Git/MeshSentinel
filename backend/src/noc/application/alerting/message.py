"""Mensaje de notificación desacoplado del proveedor.

`render_message` produce una estructura neutra (`NotificationMessage`) a
partir de una `Alert`; cada proveedor (`noc.adapters.notifications`) formatea
ESA estructura a su propio formato de cable, sin duplicar la lógica de
títulos/prioridades por severidad en cada adapter.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from noc.domain.alerts.entities import Alert, Severity

_KIND_PREFIX = {"fired": "ALERTA", "reminder": "RECORDATORIO", "resolved": "RESUELTA", "test": "TEST"}


@dataclass(slots=True, frozen=True)
class NotificationMessage:
    title: str
    severity: Severity
    kind: str  # "fired" | "reminder" | "resolved" | "test"
    subject_label: str
    body: str
    occurred_at: datetime


def render_message(alert: Alert, kind: str) -> NotificationMessage:
    prefix = _KIND_PREFIX.get(kind, kind.upper())
    subject_label = f"{alert.subject_type}:{alert.subject_id}"
    title = f"[{prefix}] {alert.severity}: {alert.rule_name}"
    occurred_at = (
        {"resolved": alert.resolved_at, "fired": alert.fired_at}.get(kind) or alert.fired_at or datetime.now(timezone.utc)
    )
    return NotificationMessage(
        title=title,
        severity=alert.severity,
        kind=kind,
        subject_label=subject_label,
        body=alert.message,
        occurred_at=occurred_at,
    )


def test_message() -> NotificationMessage:
    """Mensaje canned para el botón de prueba de un proveedor suelto, sin
    Alert real detrás — usado tanto por `provider.test()` como por la ruta
    `/notification-providers/{id}/test`."""
    return NotificationMessage(
        title="[TEST] INFO: Prueba de integración",
        severity="INFO",
        kind="test",
        subject_label="system:noc",
        body="Mensaje de prueba — Meshtastic NOC",
        occurred_at=datetime.now(timezone.utc),
    )
