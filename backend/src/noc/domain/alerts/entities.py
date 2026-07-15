"""Entidades del motor de alertas. Sin dependencias de infraestructura."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Severity = Literal["INFO", "WARNING", "CRITICAL"]
AlertStatus = Literal["firing", "acknowledged", "resolved"]

# Estados considerados "activos": la condición sigue presente
ACTIVE_STATUSES: tuple[AlertStatus, ...] = ("firing", "acknowledged")


@dataclass(slots=True)
class AlertRule:
    name: str
    rule_type: str
    severity: Severity
    enabled: bool = True
    # Columnas comunes consultables en SQL; `params` solo para extras por tipo
    threshold: float | None = None
    duration_seconds: int | None = None
    cooldown_seconds: int = 0  # 0 = sin recordatorios mientras siga firing
    params: dict[str, Any] = field(default_factory=dict)
    # Reglas por grupo (motor-de-reglas-y-topologia.md §1.3, opción A):
    # None = regla global; con valor, el motor la evalúa SOLO sobre los
    # nodos miembros de ese grupo (umbral diferenciado por grupo).
    group_id: int | None = None
    # Reglas por nodo individual: mutuamente excluyente con group_id
    # (validado en la API) — vigilar un solo nodo en vez de toda la red o
    # un grupo.
    node_id: str | None = None
    # Canales lógicos a los que despachar (N:M vía alert_rule_channels, no es
    # columna propia): vacío = broadcast a todos los proveedores enabled
    # (compat con el comportamiento previo a esta ampliación).
    channel_ids: list[int] = field(default_factory=list)
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Alert:
    rule_id: int
    rule_name: str
    subject_type: Literal["node", "gateway", "system"]
    subject_id: str
    severity: Severity
    message: str
    status: AlertStatus = "firing"
    # Preparado para agrupar alertas de una misma incidencia (sin lógica aún)
    correlation_key: str | None = None
    id: int | None = None
    fired_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    last_notified_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


@dataclass(slots=True)
class NotificationProviderConfig:
    """Instancia de proveedor configurada (p.ej. "bot de Telegram del
    equipo"). `provider` es un registro extensible por string (ver
    noc.adapters.notifications.PROVIDERS)."""

    name: str
    provider: str  # "webhook" | "ntfy" | "telegram" (registro extensible)
    configuration: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class NotificationChannel:
    """Canal LÓGICO que las reglas conocen (p.ej. "Operadores", "Guardia").

    Agrupa 1+ proveedores; `provider_ids` se carga/guarda vía el repo
    (tabla puente notification_channel_providers), no es una columna propia
    — mismo patrón que tags/grupos de nodos (M1.2)."""

    name: str
    description: str | None = None
    provider_ids: list[int] = field(default_factory=list)
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AlertCondition:
    """Condición activa detectada por un evaluador.

    Es la moneda de cambio del motor: cualquier fuente (evaluación periódica
    hoy; eventos puntuales en el futuro) produce AlertCondition y el motor las
    reconcilia contra las alertas activas. Clave de deduplicación:
    (rule_id, subject_type, subject_id).
    """

    rule_id: int
    subject_type: Literal["node", "gateway", "system"]
    subject_id: str
    message: str
    correlation_key: str | None = None
