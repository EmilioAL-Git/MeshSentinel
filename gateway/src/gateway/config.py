from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    gateway_id: str = "gw-01"
    log_level: str = "INFO"

    transport: Literal["serial", "tcp", "http", "simulated"] = "simulated"
    serial_device: str = "/dev/ttyUSB0"
    tcp_host: str = ""
    tcp_port: int = 4403
    http_url: str = ""

    redis_url: str = "redis://redis:6379/0"
    events_channel: str = "noc:events"
    commands_stream_prefix: str = "noc:commands:"
    commands_consumer_group: str = "gateway"

    status_interval_seconds: int = 30

    # Transporte simulado (ADR 0007)
    sim_node_count: int = 12
    sim_seed: int = 42
    sim_telemetry_interval_seconds: int = 15
    sim_center_lat: float = 40.4168
    sim_center_lon: float = -3.7038

    @property
    def commands_stream(self) -> str:
        return f"{self.commands_stream_prefix}{self.gateway_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
