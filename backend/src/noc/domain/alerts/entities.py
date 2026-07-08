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
class NotificationChannelConfig:
    name: str
    channel_type: str  # "webhook" | "ntfy" (registro extensible)
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    id: int | None = None


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
