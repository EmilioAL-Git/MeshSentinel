from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOC_", env_file=".env", extra="ignore")

    app_name: str = "Meshtastic NOC"
    version: str = "0.1.0"
    # Inyectados en build (Dockerfile ARG -> ENV); "unknown" en desarrollo local
    git_commit: str = "unknown"
    build_time: str = "unknown"
    environment: str = "production"
    log_level: str = "INFO"

    # PostgreSQL recomendado (ADR 0004); SQLite soportado:
    #   sqlite+aiosqlite:////data/noc.db
    database_url: str = "postgresql+asyncpg://noc:noc@postgres:5432/noc"

    redis_url: str = "redis://redis:6379/0"
    events_channel: str = "noc:events"
    commands_stream_prefix: str = "noc:commands:"

    # Un nodo se considera offline si no se ha oído en este intervalo
    node_offline_after_seconds: int = 900
    # Una pasarela se considera caída sin latido en este intervalo
    # (el gateway emite gateway.status cada GATEWAY_STATUS_INTERVAL_SECONDS=30)
    gateway_stale_after_seconds: int = 90

    # ── Umbrales del Dashboard NOC (Fase 3B) ─────────────────────────
    low_battery_threshold: int = Field(
        default=20, validation_alias=AliasChoices("LOW_BATTERY_THRESHOLD", "NOC_LOW_BATTERY_THRESHOLD")
    )
    offline_minutes_warning: int = Field(
        default=30, validation_alias=AliasChoices("OFFLINE_MINUTES_WARNING", "NOC_OFFLINE_MINUTES_WARNING")
    )
    offline_percent_warning: float = Field(
        default=5, validation_alias=AliasChoices("OFFLINE_PERCENT_WARNING", "NOC_OFFLINE_PERCENT_WARNING")
    )
    offline_percent_critical: float = Field(
        default=20,
        validation_alias=AliasChoices("OFFLINE_PERCENT_CRITICAL", "NOC_OFFLINE_PERCENT_CRITICAL"),
    )
    snr_degraded_threshold: float = Field(
        default=-15, validation_alias=AliasChoices("SNR_DEGRADED_THRESHOLD", "NOC_SNR_DEGRADED_THRESHOLD")
    )
    dashboard_cache_seconds: float = 5.0

    # Cadencia del motor de alertas (Fase 3C, ADR 0012)
    alert_eval_interval_seconds: float = 30.0

    # ── Pipeline de administración remota (M1.1, ADR 0013) ───────────
    # Presupuesto de malla: operaciones despachadas por minuto (global). El
    # valor de M1.1 (6) era excesivamente conservador: con presets rápidos
    # (EU_868) el límite regulatorio de duty cycle (10%) admite muchos más
    # intercambios cortos por minuto. Sigue siendo un techo de seguridad, no
    # el throughput real (lo limita también "1 operación en vuelo por
    # gateway" + la latencia real de cada roundtrip).
    admin_rate_limit_per_minute: int = 60
    admin_default_timeout_seconds: int = 120
    admin_max_attempts: int = 3
    admin_scheduler_interval_seconds: float = 2.0
    # Gracia antes de dar por colgada una operación en vuelo sin respuesta
    admin_watchdog_grace_seconds: int = 30
    # Backoff de reintento por fallo: base * 2^(intentos-1), tope en el máximo
    admin_retry_base_seconds: int = 10
    admin_retry_max_seconds: int = 300
    # ADR 0019 errata 4: pausa fija (no backoff) antes de un reenvío
    # redundante de favorito/ignorado remoto ya "confirmado" por ACK aislado
    admin_redundant_resend_seconds: int = 5

    # ── Registro persistente (hardening) ─────────────────────────────
    # Tope de filas de activity_log: el escritor poda las más antiguas al
    # superarlo (diario operativo con memoria, no histórico ilimitado).
    activity_log_max_rows: int = 20_000

    # ── Autenticación ──────────────────────────────────────────────────
    # Modo abierto mientras no exista ningún auth_users con is_admin+enabled
    # (sin flag de entorno: ver AuthService.is_protected_mode). Sesión
    # deslizante: se renueva en cada request autenticada válida hasta un tope
    # absoluto — evita tanto sesiones eternas como cerrar sesión a media
    # jornada de un operador de guardia.
    session_cookie_name: str = "ms_session"
    session_idle_hours: int = 12
    session_max_days: int = 7
    # El stack por defecto sirve HTTP plano (nginx :80, sin TLS): una cookie
    # `Secure` es rechazada por el navegador desde cualquier host que no sea
    # localhost, y el login parecería funcionar (200) sin dejar sesión. Por
    # eso el default es false; con TLS delante SIEMPRE debe ir a true.
    cookie_secure: bool = False
    password_min_length: int = 10
    login_rate_limit_window_seconds: int = 900
    login_rate_limit_per_username: int = 5
    login_rate_limit_per_ip: int = 20

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
