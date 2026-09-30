"""API HTTP interna del lanzador de gateways (ADR 0028).

Nunca se expone fuera de la red interna de Docker (sin puertos publicados
en docker-compose.yml) — es la única superficie con la que el backend habla
para crear/destruir contenedores; el backend nunca monta el socket de
Docker directamente.
"""

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from launcher.config import get_settings
from launcher.devices import list_usb_devices
from launcher.docker_client import (
    ContainerAlreadyExists,
    ContainerNotFound,
    InvalidGatewayId,
    LauncherDockerClient,
)

logger = logging.getLogger("launcher")

app = FastAPI(title="gateway-launcher", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    app.state.docker = LauncherDockerClient(settings)


class DeviceOut(BaseModel):
    port: str
    description: str | None = None
    vid: str | None = None
    pid: str | None = None
    serial_number: str | None = None


class ContainerOut(BaseModel):
    gateway_id: str
    container_id: str
    name: str
    status: str


class CreateContainerIn(BaseModel):
    gateway_id: str = Field(min_length=1, max_length=63)
    transport_type: str = Field(pattern="^(usb|tcp|simulated)$")
    connection_params: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/devices", response_model=list[DeviceOut])
async def devices() -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_usb_devices)


@app.get("/containers", response_model=list[ContainerOut])
async def list_containers() -> list[Any]:
    return await asyncio.to_thread(app.state.docker.list_containers)


@app.post("/containers", response_model=ContainerOut)
async def create_container(body: CreateContainerIn) -> Any:
    try:
        return await asyncio.to_thread(
            app.state.docker.create_container, body.gateway_id, body.transport_type, body.connection_params
        )
    except InvalidGatewayId as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContainerAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/containers/{gateway_id}", status_code=204)
async def destroy_container(gateway_id: str) -> None:
    try:
        await asyncio.to_thread(app.state.docker.destroy_container, gateway_id)
    except ContainerNotFound as exc:
        raise HTTPException(status_code=404, detail="Contenedor no encontrado") from exc
