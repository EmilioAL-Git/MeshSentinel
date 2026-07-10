from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    # OJO: con env_prefix, pydantic-settings resolvería "GATEWAY_GATEWAY_ID";
    # el alias explícito hace funcionar GATEWAY_ID, que es lo que documentan
    # .env.example y docker-compose desde Fase 0. Bug latente hasta M6.2:
    # con un solo proceso el default "gw-01" coincidía y nadie lo notó.
    gateway_id: str = Field(default="gw-01", validation_alias=AliasChoices("GATEWAY_ID"))
    log_level: str = "INFO"

    transport: Literal["usb", "tcp", "http", "simulated"] = "simulated"
    tcp_host: str = ""
    tcp_port: int = 4403
    http_url: str = ""

    # USB (librería oficial; sin baudrate: lo gestiona la propia librería)
    # Vacío = autodetección con meshtastic.util.findPorts()
    usb_device: str = Field(
        default="", validation_alias=AliasChoices("MESHTASTIC_USB_DEVICE", "GATEWAY_USB_DEVICE")
    )
    reconnect_initial_delay: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "MESHTASTIC_RECONNECT_INITIAL_DELAY", "GATEWAY_RECONNECT_INITIAL_DELAY"
        ),
    )
    reconnect_max_delay: float = Field(
        default=300.0,
        validation_alias=AliasChoices(
            "MESHTASTIC_RECONNECT_MAX_DELAY", "GATEWAY_RECONNECT_MAX_DELAY"
        ),
    )
    # Espera entre enviar un SET y leer la verificación (M1.3)
    set_settle_seconds: float = 3.0

    @field_validator("transport", mode="before")
    @classmethod
    def _transport_aliases(cls, v: str) -> str:
        aliases = {"simulator": "simulated", "serial": "usb"}
        return aliases.get(str(v).lower(), str(v).lower())

    redis_url: str = "redis://redis:6379/0"
    events_channel: str = "noc:events"
    commands_stream_prefix: str = "noc:commands:"
    commands_consumer_group: str = "gateway"

    status_interval_seconds: int = 30

    # Transporte simulado (ADR 0007)
    sim_node_count: int = 12
    sim_seed: int = 42
    # M6.2 (Multi-Gateway): nodos "compartidos" deterministas por semilla
    # común — dos procesos gateway con el MISMO sim_shared_seed generan
    # exactamente los mismos nodos compartidos (mismos node_id) además de sus
    # nodos exclusivos de sim_seed, poblando node_gateway_links con solape
    # real. 0 = sin nodos compartidos (comportamiento previo, por defecto).
    sim_shared_seed: int = 0
    sim_shared_node_count: int = 4
    sim_telemetry_interval_seconds: int = 15
    sim_center_lat: float = 40.4168
    sim_center_lon: float = -3.7038

    @property
    def commands_stream(self) -> str:
        return f"{self.commands_stream_prefix}{self.gateway_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
