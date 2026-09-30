"""Cliente HTTP interno de `gateway-launcher` (ADR 0028).

El backend nunca monta el socket de Docker — le pide a este sidecar aparte
que cree/destruya contenedores. Solo se llama desde `GatewayService`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("noc.gateways.launcher")


class LauncherError(Exception):
    """El lanzador respondió con un error (params inválidos, Docker rechazó
    la operación) o no respondió en absoluto (no desplegado, caído)."""


class LauncherContainerNotFound(LauncherError):
    """404 al destruir: no hay contenedor nuestro con ese gateway_id — el
    llamante puede tratarlo como éxito idempotente si lo que quería era
    justamente que no exista."""


class GatewayLauncherClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def list_devices(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(f"{self._base_url}/devices")
            except httpx.HTTPError as exc:
                raise LauncherError(f"gateway-launcher no responde: {exc}") from exc
        if resp.status_code != 200:
            raise LauncherError(f"gateway-launcher devolvió {resp.status_code}: {resp.text}")
        return resp.json()

    async def create_container(
        self, gateway_id: str, transport_type: str, connection_params: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}/containers",
                    json={
                        "gateway_id": gateway_id,
                        "transport_type": transport_type,
                        "connection_params": connection_params,
                    },
                )
            except httpx.HTTPError as exc:
                raise LauncherError(f"gateway-launcher no responde: {exc}") from exc
        if resp.status_code >= 400:
            raise LauncherError(_error_detail(resp))
        return resp.json()

    async def destroy_container(self, gateway_id: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.delete(f"{self._base_url}/containers/{gateway_id}")
            except httpx.HTTPError as exc:
                raise LauncherError(f"gateway-launcher no responde: {exc}") from exc
        if resp.status_code == 404:
            raise LauncherContainerNotFound(gateway_id)
        if resp.status_code >= 400:
            raise LauncherError(_error_detail(resp))


def _error_detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))
    except ValueError:
        return resp.text
