"""Registro de ajustes operacionales editables en runtime (panel "Ajustes").

Cero lógica por parámetro (mismo criterio que el editor de configuración de
nodo, ADR 0015): cada entrada describe un campo de `noc.config.Settings` con
metadatos suficientes para que el frontend genere el control sin conocer su
significado. Solo cubre umbrales operacionales del backend — wiring de
infraestructura (BD, Redis, CORS...), los defaults de fábrica por rule_type
del motor de alertas (editables por regla individual en Alertas) y los
ajustes del propio proceso gateway quedan fuera a propósito.
"""

from dataclasses import dataclass
from typing import Any

from noc.config import Settings


@dataclass(slots=True, frozen=True)
class SettingSpec:
    key: str  # nombre del campo en Settings
    category: str
    label: str
    value_type: str  # "int" | "float"
    unit: str | None = None
    min_value: float | None = None
    description: str = ""


CATEGORY_LABELS: dict[str, str] = {
    "network": "Red y nodos",
    "alerts": "Motor de alertas",
    "admin": "Administración remota",
    "activity": "Actividad y registro",
}

SETTINGS_REGISTRY: list[SettingSpec] = [
    SettingSpec(
        "node_offline_after_seconds", "network", "Nodo sin actividad → offline",
        "int", "s", 30,
        "Silencio tras el cual un nodo se considera offline en toda la aplicación.",
    ),
    SettingSpec(
        "gateway_stale_after_seconds", "network", "Pasarela sin latido → caída",
        "int", "s", 15,
        "El gateway emite un latido cada 30 s; pasado este tiempo sin uno se considera caída.",
    ),
    SettingSpec(
        "low_battery_threshold", "network", "Batería baja",
        "int", "%", 1,
        "Umbral de aviso de batería baja en el Dashboard, Flota y alertas.",
    ),
    SettingSpec(
        "offline_minutes_warning", "network", "Minutos offline → aviso",
        "int", "min", 1,
        "Minutos sin actividad de un nodo que activan un aviso en la situación de red.",
    ),
    SettingSpec(
        "offline_percent_warning", "network", "% de flota offline → aviso",
        "float", "%", 0,
        "Porcentaje de nodos offline que sube el estado de la red a aviso.",
    ),
    SettingSpec(
        "offline_percent_critical", "network", "% de flota offline → crítico",
        "float", "%", 0,
        "Porcentaje de nodos offline que sube el estado de la red a crítico.",
    ),
    SettingSpec(
        "snr_degraded_threshold", "network", "SNR degradado",
        "float", "dB", None,
        "SNR por debajo del cual un enlace se considera degradado.",
    ),
    SettingSpec(
        "alert_eval_interval_seconds", "alerts", "Cadencia de evaluación",
        "float", "s", 5,
        "Cada cuánto se re-evalúan todas las reglas de alerta.",
    ),
    SettingSpec(
        "admin_rate_limit_per_minute", "admin", "Presupuesto de malla",
        "int", "op/min", 1,
        "Techo de operaciones de administración remota despachadas por minuto (global, duty cycle).",
    ),
    SettingSpec(
        "admin_default_timeout_seconds", "admin", "Timeout por operación",
        "int", "s", 5,
        "Tiempo máximo de espera de una operación admin antes de darla por colgada.",
    ),
    SettingSpec(
        "admin_max_attempts", "admin", "Reintentos máximos",
        "int", None, 1,
        "Número máximo de intentos de una operación admin antes de marcarla como fallida.",
    ),
    SettingSpec(
        "admin_watchdog_grace_seconds", "admin", "Gracia del vigilante",
        "int", "s", 5,
        "Margen extra sobre el timeout antes de que el vigilante dé una operación por colgada.",
    ),
    SettingSpec(
        "admin_retry_base_seconds", "admin", "Reintento: espera base",
        "int", "s", 1,
        "Espera antes del primer reintento por fallo (backoff exponencial desde aquí).",
    ),
    SettingSpec(
        "admin_retry_max_seconds", "admin", "Reintento: espera máxima",
        "int", "s", 1,
        "Techo del backoff exponencial entre reintentos por fallo.",
    ),
    SettingSpec(
        "admin_redundant_resend_seconds", "admin", "Pausa de reenvío redundante",
        "int", "s", 1,
        "Pausa fija antes de reenviar favorito/ignorado remoto ya confirmado por ACK aislado (ADR 0019).",
    ),
    SettingSpec(
        "activity_log_max_rows", "activity", "Tope del registro",
        "int", "filas", 100,
        "Filas máximas de activity_log; se podan las más antiguas al superarlo.",
    ),
]

SETTINGS_BY_KEY: dict[str, SettingSpec] = {s.key: s for s in SETTINGS_REGISTRY}


class SettingValidationError(ValueError):
    pass


def coerce_value(spec: SettingSpec, raw: Any) -> int | float:
    """Valida y castea un valor entrante contra su SettingSpec. Lanza
    SettingValidationError (mensaje de operador) si no cumple tipo/rango."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SettingValidationError(f"{spec.label}: se esperaba un número")
    value = int(raw) if spec.value_type == "int" else float(raw)
    if spec.min_value is not None and value < spec.min_value:
        raise SettingValidationError(f"{spec.label}: mínimo {spec.min_value}{spec.unit or ''}")
    return value


def apply_overrides(settings: Settings, overrides: dict[str, Any]) -> None:
    """Aplica overrides de BD sobre la instancia COMPARTIDA de Settings
    (get_settings() es @lru_cache: un único objeto para todo el proceso) —
    los servicios ya construidos que guardaron una referencia a `settings`
    ven el cambio sin reiniciar ni recablear nada."""
    for key, raw in overrides.items():
        spec = SETTINGS_BY_KEY.get(key)
        if spec is None:
            continue  # clave obsoleta (ajuste retirado de una versión anterior)
        try:
            setattr(settings, key, coerce_value(spec, raw))
        except SettingValidationError:
            continue  # override corrupto en BD: se ignora, prevalece el default
