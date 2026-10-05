"""Ciclo de vida de contenedores gateway sobre el socket de Docker (ADR 0028).

Única pieza de este servicio que habla con `dockerd`. Toda operación
destructiva (destroy) se limita a contenedores con la etiqueta
`label_key=true` — nunca toca nada que el lanzador no haya creado él mismo.
Las llamadas al SDK `docker` (síncrono) se ejecutan en `asyncio.to_thread`
desde `main.py`; este módulo en sí es síncrono a propósito, sin mezclar
asyncio con el cliente Docker.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import APIError, NotFound

from launcher.config import Settings

# gateway_id ya es válido como PK de texto en el backend; aquí además debe
# poder ser nombre de contenedor Docker sin sorpresas — alfanumérico, guion,
# guion bajo y punto, como exige la propia API de Docker.
_GATEWAY_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")


class InvalidGatewayId(ValueError):
    pass


class ContainerAlreadyExists(RuntimeError):
    """Ya existe un contenedor con ese nombre y NO es nuestro (sin la
    etiqueta del lanzador) — no se sobreescribe nada ajeno."""


class ContainerNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ContainerInfo:
    gateway_id: str
    container_id: str
    name: str
    status: str


def _validate_gateway_id(gateway_id: str) -> str:
    if not _GATEWAY_ID_RE.match(gateway_id):
        raise InvalidGatewayId(
            f"gateway_id inválido: «{gateway_id}» (solo alfanumérico, '-', '_', '.', máx. 63)"
        )
    return gateway_id


def _container_name(settings: Settings, gateway_id: str) -> str:
    return f"{settings.container_name_prefix}{gateway_id}"


def _build_env(settings: Settings, gateway_id: str, transport_type: str, connection_params: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {
        "GATEWAY_ID": gateway_id,
        "GATEWAY_REDIS_URL": settings.gateway_redis_url,
        "GATEWAY_TRANSPORT": transport_type,
    }
    if transport_type == "usb":
        device = connection_params.get("device")
        if device:
            env["MESHTASTIC_USB_DEVICE"] = str(device)
    elif transport_type == "tcp":
        host = connection_params.get("host")
        if not host:
            raise ValueError("transporte tcp requiere 'host' en connection_params")
        env["GATEWAY_TCP_HOST"] = str(host)
        port = connection_params.get("port")
        if port:
            env["GATEWAY_TCP_PORT"] = str(port)
    elif transport_type == "http":
        host = connection_params.get("host")
        if not host:
            raise ValueError("transporte http requiere 'host' en connection_params")
        env["GATEWAY_HTTP_HOST"] = str(host)
        if connection_params.get("port"):
            env["GATEWAY_HTTP_PORT"] = str(connection_params["port"])
    elif transport_type == "mqtt":
        host = connection_params.get("host")
        if not host:
            raise ValueError("transporte mqtt requiere 'host' en connection_params")
        env["GATEWAY_MQTT_HOST"] = str(host)
        for key, env_key in (
            ("port", "GATEWAY_MQTT_PORT"),
            ("username", "GATEWAY_MQTT_USERNAME"),
            ("password", "GATEWAY_MQTT_PASSWORD"),
            ("topic", "GATEWAY_MQTT_TOPIC"),
            ("psk", "GATEWAY_MQTT_PSK"),
        ):
            if connection_params.get(key) not in (None, ""):
                env[env_key] = str(connection_params[key])
        if connection_params.get("tls"):
            env["GATEWAY_MQTT_TLS"] = "true"
        # dict/list: pydantic-settings los lee como JSON desde el entorno
        for key, env_key in (("channel_keys", "GATEWAY_MQTT_CHANNEL_KEYS"), ("geo_bbox", "GATEWAY_MQTT_GEO_BBOX")):
            if connection_params.get(key):
                env[env_key] = json.dumps(connection_params[key])
    elif transport_type == "simulated":
        for key, env_key in (
            ("seed", "GATEWAY_SIM_SEED"),
            ("node_count", "GATEWAY_SIM_NODE_COUNT"),
            ("shared_seed", "GATEWAY_SIM_SHARED_SEED"),
            ("shared_node_count", "GATEWAY_SIM_SHARED_NODE_COUNT"),
        ):
            value = connection_params.get(key)
            if value is not None:
                env[env_key] = str(value)
    else:
        raise ValueError(f"transporte no soportado por el lanzador: «{transport_type}»")
    if transport_type != "mqtt" and connection_params.get("vn_enabled"):
        # Nodo virtual (ADR 0033): el puerto lo publica el contenedor en el host
        env["GATEWAY_VN_ENABLED"] = "true"
        env["GATEWAY_VN_PORT"] = str(connection_params.get("vn_port") or 4404)
        if connection_params.get("vn_allow_admin"):
            env["GATEWAY_VN_ALLOW_ADMIN"] = "true"
    return env


def _ports_kwarg(transport_type: str, connection_params: dict[str, Any]) -> dict[str, int] | None:
    """Puerto del nodo virtual publicado en el host (mismo número dentro y fuera)."""
    if transport_type == "mqtt" or not connection_params.get("vn_enabled"):
        return None
    port = int(connection_params.get("vn_port") or 4404)
    return {f"{port}/tcp": port}


def _devices_kwarg(transport_type: str, connection_params: dict[str, Any]) -> list[str] | None:
    if transport_type != "usb":
        return None
    device = connection_params.get("device")
    if not device:
        return None
    device = str(device)
    if not os.path.exists(device):
        raise ValueError(f"el dispositivo «{device}» no existe en el host (¿se desconectó?)")
    return [f"{device}:{device}"]


class LauncherDockerClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = docker.from_env()

    def list_containers(self) -> list[ContainerInfo]:
        containers = self._client.containers.list(
            all=True, filters={"label": f"{self._settings.label_key}=true"}
        )
        result: list[ContainerInfo] = []
        for c in containers:
            gateway_id = c.labels.get(self._settings.label_id_key)
            if not gateway_id:
                continue
            result.append(ContainerInfo(gateway_id=gateway_id, container_id=c.id, name=c.name, status=c.status))
        return result

    def create_container(
        self, gateway_id: str, transport_type: str, connection_params: dict[str, Any]
    ) -> ContainerInfo:
        _validate_gateway_id(gateway_id)
        settings = self._settings
        name = _container_name(settings, gateway_id)
        env = _build_env(settings, gateway_id, transport_type, connection_params)
        devices = _devices_kwarg(transport_type, connection_params)

        # Recreación idempotente: si YA existe un contenedor nuestro con este
        # gateway_id (p. ej. reintento tras un fallo a medias), se destruye
        # primero. Si existe pero no es nuestro (sin la etiqueta), se aborta
        # sin tocar nada ajeno.
        try:
            existing = self._client.containers.get(name)
        except NotFound:
            existing = None
        if existing is not None:
            if existing.labels.get(settings.label_key) != "true":
                raise ContainerAlreadyExists(
                    f"ya existe un contenedor «{name}» ajeno al lanzador — elige otro gateway_id"
                )
            _remove(existing)

        labels = {settings.label_key: "true", settings.label_id_key: gateway_id}
        try:
            container = self._client.containers.run(
                settings.gateway_image,
                name=name,
                environment=env,
                labels=labels,
                network=settings.docker_network,
                devices=devices,
                ports=_ports_kwarg(transport_type, connection_params),
                restart_policy={"Name": "unless-stopped"},
                detach=True,
            )
        except APIError as exc:
            raise RuntimeError(f"Docker rechazó la creación del contenedor: {exc}") from exc
        return ContainerInfo(gateway_id=gateway_id, container_id=container.id, name=name, status=container.status)

    def destroy_container(self, gateway_id: str) -> None:
        settings = self._settings
        name = _container_name(settings, gateway_id)
        try:
            container = self._client.containers.get(name)
        except NotFound:
            raise ContainerNotFound(gateway_id) from None
        if container.labels.get(settings.label_key) != "true":
            # No debería poder pasar (el nombre lleva nuestro prefijo), pero
            # es la última barrera antes de una operación destructiva.
            raise ContainerNotFound(gateway_id)
        _remove(container)


def _remove(container: Any) -> None:
    try:
        container.remove(force=True)
    except NotFound:
        pass
