"""Gestión en caliente del transporte activo (M5, ADR 0021).

Sustituye la creación estática de `create_transport()` en el arranque: crea,
sustituye y destruye instancias de `Transport` en respuesta a comandos
`command.gateway_*` recibidos por el stream de comandos existente (ADR 0003).
No conoce SQL ni HTTP del backend — solo Settings/Transport/EmitFn, igual que
el resto de `gateway/`.
"""

import asyncio
import logging
import uuid
from typing import Any

from gateway.config import Settings
from gateway.transports.base import EmitFn, Transport
from gateway.transports.factory import create_transport

logger = logging.getLogger("gateway.transport_manager")

# Nombres de campo de Settings que cada transporte acepta desde connection_params
_PARAM_FIELDS: dict[str, dict[str, str]] = {
    "usb": {"device": "usb_device"},
    "tcp": {"host": "tcp_host", "port": "tcp_port"},
    "http": {"url": "http_url"},
    "simulated": {},
}


def _apply_connection_params(base: Settings, transport_type: str, params: dict[str, Any]) -> Settings:
    fields = _PARAM_FIELDS.get(transport_type, {})
    update: dict[str, Any] = {"transport": transport_type}
    for param_key, settings_field in fields.items():
        if param_key in params and params[param_key] is not None:
            update[settings_field] = params[param_key]
    return base.model_copy(update=update)


class TransportManager:
    def __init__(self, base_settings: Settings, publish: EmitFn) -> None:
        self._base_settings = base_settings
        self._publish = publish
        self._transport: Transport | None = None
        self._task: asyncio.Task[None] | None = None
        self._generation = 0
        self._outcome: asyncio.Future[tuple[str, str | None]] | None = None

    @property
    def transport(self) -> Transport | None:
        return self._transport

    async def start_from_env(self) -> None:
        """Arranque del proceso: comportamiento de hoy, sin comandos (compatibilidad)."""
        await self._start(self._base_settings)

    async def _emit_tracked(self, event_type: str, payload: dict[str, Any], generation: int) -> None:
        await self._publish(event_type, payload)
        if event_type != "gateway.status" or generation != self._generation:
            return
        status = payload.get("status")
        outcome = self._outcome
        if status in ("connected", "error") and outcome is not None and not outcome.done():
            outcome.set_result((status, payload.get("detail")))

    async def _start(self, settings: Settings, wait_timeout: float | None = None) -> tuple[str, str | None] | None:
        await self.teardown()
        self._generation += 1
        generation = self._generation
        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[tuple[str, str | None]] | None = None
        if wait_timeout is not None:
            outcome = loop.create_future()
        self._outcome = outcome

        async def emit(event_type: str, payload: dict[str, Any]) -> None:
            await self._emit_tracked(event_type, payload, generation)

        transport = create_transport(settings, emit)
        self._transport = transport
        self._task = asyncio.create_task(transport.run(), name="transport")

        if outcome is None:
            return None
        try:
            return await asyncio.wait_for(outcome, timeout=wait_timeout)
        except asyncio.TimeoutError:
            return ("timeout", None)

    async def connect(self, transport_type: str, connection_params: dict[str, Any]) -> None:
        settings = _apply_connection_params(self._base_settings, transport_type, connection_params)
        await self._start(settings)

    async def test_connection(
        self, transport_type: str, connection_params: dict[str, Any], timeout: float = 25.0
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        settings = _apply_connection_params(self._base_settings, transport_type, connection_params)
        status, detail = await self._start(settings, wait_timeout=timeout) or ("timeout", None)
        if status != "connected":
            await self.teardown()
            error = detail or ("sin respuesta del transporte" if status == "timeout" else "fallo de conexión")
            return {"request_id": request_id, "ok": False, "error": error}
        transport = self._transport
        return {
            "request_id": request_id,
            "ok": True,
            "error": None,
            "local_node_id": transport.local_node_id if transport else None,
            "local_short_name": getattr(transport, "local_short_name", None),
            "local_long_name": getattr(transport, "local_long_name", None),
            "local_hw_model": getattr(transport, "local_hw_model", None),
            "local_firmware_version": getattr(transport, "local_firmware_version", None),
        }

    async def disconnect(self) -> None:
        transport_name = self._transport.name if self._transport is not None else self._base_settings.transport
        await self.teardown()
        await self._publish(
            "gateway.status",
            {
                "status": "unassigned",
                "transport": transport_name,
                "local_node_id": None,
                "detail": "disconnected by user",
                "local_short_name": None,
                "local_long_name": None,
                "local_hw_model": None,
                "local_firmware_version": None,
            },
        )

    async def discover(self) -> dict[str, Any]:
        from gateway.transports.usb import MeshtasticUsbTransport

        request_id = str(uuid.uuid4())
        devices = await asyncio.to_thread(MeshtasticUsbTransport.discover_devices)
        return {"request_id": request_id, "devices": devices}

    async def teardown(self) -> None:
        self._generation += 1  # invalida cualquier outcome pendiente de la conexión anterior
        if self._outcome is not None and not self._outcome.done():
            self._outcome.cancel()
        self._outcome = None
        transport, task = self._transport, self._task
        self._transport, self._task = None, None
        if transport is not None:
            try:
                await transport.close()
            except Exception:
                logger.exception("transport_manager.close_error")
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
