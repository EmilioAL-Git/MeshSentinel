from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config del lanzador (ADR 0028). Prefijo propio (LAUNCHER_) — no
    comparte espacio de nombres con NOC_ (backend) ni GATEWAY_ (proceso
    gateway), es un componente de primer nivel aparte."""

    model_config = SettingsConfigDict(env_prefix="LAUNCHER_", env_file=".env", extra="ignore")

    log_level: str = "INFO"

    # Imagen que se instancia al crear un contenedor gateway. Debe coincidir
    # con la etiqueta explícita que docker-compose.yml pone al servicio
    # `gateway` (build) — un nombre estable, independiente de cómo Compose
    # nombre sus propias imágenes según el directorio del proyecto.
    gateway_image: str = "meshsentinel-gateway:local"
    # Red a la que se adjunta cada contenedor creado — debe ser la misma red
    # nombrada explícita en docker-compose.yml (para que backend/redis y el
    # contenedor nuevo se vean por nombre de servicio DNS).
    docker_network: str = "meshsentinel"
    # GATEWAY_REDIS_URL por defecto para los contenedores que se crean.
    gateway_redis_url: str = "redis://redis:6379/0"
    container_name_prefix: str = "meshsentinel-gateway-"
    # Etiqueta que marca un contenedor como "creado por este lanzador": toda
    # operación destructiva (destroy) se limita a contenedores con esta
    # etiqueta — nunca toca nada que no haya creado él mismo (ADR 0028 §1).
    label_key: str = "meshsentinel.gateway"
    label_id_key: str = "meshsentinel.gateway_id"


@lru_cache
def get_settings() -> Settings:
    return Settings()
