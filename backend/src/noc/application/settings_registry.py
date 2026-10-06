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
    # Presets (etiqueta, valor en la unidad nativa del campo) para renderizar un
    # desplegable en vez de un número libre. None = número libre (por defecto).
    choices: tuple[tuple[str, float], ...] | None = None


CATEGORY_LABELS: dict[str, str] = {
    "network": "Red y nodos",
    "alerts": "Motor de alertas",
    "admin": "Administración remota",
    "activity": "Actividad y registro",
    "retention": "Retención de datos",
    "digest": "Resumen periódico",
    "backup": "Copias de seguridad",
    "security": "Seguridad",
}

RETENTION_CHOICES: tuple[tuple[str, float], ...] = (
    ("Siempre", 0),
    ("7 días", 7),
    ("30 días", 30),
    ("90 días", 90),
    ("180 días", 180),
    ("1 año", 365),
)

SETTINGS_REGISTRY: list[SettingSpec] = [
    SettingSpec(
        "node_offline_after_seconds", "network", "Nodo sin actividad → offline",
        "int", "s", 30,
        "Silencio tras el cual un nodo se considera offline en toda la aplicación.",
        choices=(
            ("15 min", 900),
            ("30 min", 1800),
            ("1 h", 3600),
            ("2 h", 7200),
            ("4 h", 14400),
            ("6 h", 21600),
            ("12 h", 43200),
            ("24 h", 86400),
        ),
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
        "offline_minutes_warning", "network", "Tiempo offline → aviso",
        "int", "min", 1,
        "Minutos sin actividad de un nodo que activan un aviso en la situación de red.",
        choices=(
            ("15 min", 15),
            ("30 min", 30),
            ("1 h", 60),
            ("2 h", 120),
            ("4 h", 240),
            ("6 h", 360),
            ("12 h", 720),
            ("24 h", 1440),
        ),
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
        "activity_log_max_rows", "retention", "Registro de actividad (tope de filas)",
        "int", "filas", 100,
        "Filas máximas de activity_log; se podan las más antiguas al superarlo.",
    ),
    SettingSpec(
        "retention_telemetry_days", "retention", "Telemetría",
        "int", "d", 0,
        "Batería, voltaje, uso de canal, entorno… de cada nodo. 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_positions_days", "retention", "Posiciones",
        "int", "d", 0,
        "Historial GPS (traza en el mapa y distancia recorrida). 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_coverage_days", "retention", "Cobertura medida",
        "int", "d", 0,
        "Recepciones directas con señal (capa «Cobertura medida» del mapa). 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_neighbors_days", "retention", "Vecinos (NeighborInfo)",
        "int", "d", 0,
        "Enlaces nodo↔nodo reportados; crece rápido (N vecinos por paquete). Las alertas de enlace perdido miran 7 días. 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_traces_days", "retention", "Trazas de la red (traceroute)",
        "int", "d", 0,
        "Trazas y saltos que dibujan la red real. Son pocas y muy valiosas: conviene conservarlas mucho. 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_chat_days", "retention", "Mensajes de chat",
        "int", "d", 0,
        "Mensajes de texto oídos por las pasarelas. 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_alerts_days", "retention", "Alertas resueltas",
        "int", "d", 0,
        "Solo alertas ya resueltas; las activas y reconocidas nunca se podan. 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_admin_days", "retention", "Operaciones y lotes de administración",
        "int", "d", 0,
        "Solo operaciones terminadas y lotes finalizados. 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_nexus_days", "retention", "Operaciones Nexus",
        "int", "d", 0,
        "Solo operaciones terminadas (con sus respuestas por nodo). 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_login_log_days", "retention", "Registro de accesos",
        "int", "d", 0,
        "Intentos de login (auditoría de seguridad). 0 = conservar siempre.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "retention_nodes_days", "retention", "Nodos sin actividad",
        "int", "d", 0,
        "Borra el nodo y TODA su historia si no se le oye en este tiempo. Excluye favoritos y nodos locales de pasarela. 0 = nunca.",
        choices=RETENTION_CHOICES,
    ),
    SettingSpec(
        "digest_period_hours", "digest", "Periodicidad del resumen",
        "int", "h", 0,
        "Envía un resumen de la red a todas las integraciones de notificación habilitadas.",
        choices=(("Desactivado", 0), ("Cada día", 24), ("Cada semana", 168)),
    ),
    SettingSpec(
        "digest_hour_utc", "digest", "Hora de envío (UTC)",
        "int", "h", 0,
        "Hora del día, en UTC (0-23), a la que se envía el resumen.",
        choices=tuple((f"{h:02d}:00 UTC", h) for h in range(0, 24, 2)),
    ),
    SettingSpec(
        "backup_period_hours", "backup", "Copia automática",
        "int", "h", 0,
        "Guarda una copia lógica completa de la base de datos con esta periodicidad. "
        "Si una copia falla se avisa a las integraciones de notificación.",
        choices=(("Desactivada", 0), ("Cada 6 horas", 6), ("Cada día", 24), ("Cada semana", 168)),
    ),
    SettingSpec(
        "backup_keep", "backup", "Copias que se conservan",
        "int", None, 1,
        "Al superar este número se borran las más antiguas.",
        choices=(("3", 3), ("7", 7), ("14", 14), ("30", 30)),
    ),
    SettingSpec(
        "ws_require_auth", "security", "Canal en vivo (WebSocket)",
        "int", None, 0,
        "Con el modo protegido activo, exige sesión iniciada para recibir las actualizaciones en vivo. "
        "Sin sesión la app sigue mostrando datos, pero hay que recargar para verlos actualizados.",
        choices=(("Abierto", 0), ("Exigir sesión", 1)),
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
