from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOC_", env_file=".env", extra="ignore")

    app_name: str = "Meshtastic NOC"
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

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
