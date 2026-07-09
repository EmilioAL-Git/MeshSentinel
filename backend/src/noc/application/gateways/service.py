"""Gestión de gateways desde la aplicación (M5, ADR 0021).

Separa dos escrituras que nunca deben mezclarse en la misma llamada:
- runtime (heartbeat `gateway.status`, vía `SqlGatewayRepository.upsert`,
  invocado desde `IngestService` — este servicio nunca lo toca);
- configuración (esta clase): CRUD + comandos `command.gateway_*` dirigidos
  al mismo stream de comandos ya usado por el pipeline de administración
  remota (ADR 0003/0013). `discover()`/`test_connection()` correlacionan la
  respuesta del gateway por `request_id` con un `asyncio.Future` en memoria
  (nunca persistido: son peticiones síncronas de la UI, no estado de dominio).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.application.envelopes import make_command_envelope
from noc.domain.nodes.entities import GatewayInfo

logger = logging.getLogger("noc.gateways")

DISCOVER_TIMEOUT_SECONDS = 15.0
TEST_CONNECTION_TIMEOUT_SECONDS = 30.0


class GatewayService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        command_queue: RedisCommandQueue,
    ) -> None:
        self._session_factory = session_factory
        self._queue = command_queue
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}

    # ── Lectura ──────────────────────────────────────────────────────────────

    async def list_all(self, include_deleted: bool = False) -> list[GatewayInfo]:
        async with self._session_factory() as session:
            return await SqlGatewayRepository(session).list_all(include_deleted)

    async def get(self, gateway_id: str) -> GatewayInfo | None:
        async with self._session_factory() as session:
            return await SqlGatewayRepository(session).get(gateway_id)

    # ── Descubrimiento y prueba de conexión (correlación por request_id) ────

    async def discover(self, gateway_id: str) -> list[dict[str, Any]]:
        request_id = str(uuid.uuid4())
        await self._send_command(gateway_id, "command.gateway_discover", {"request_id": request_id})
        result = await self._wait_for(request_id, DISCOVER_TIMEOUT_SECONDS)
        return list(result.get("devices", [])) if result else []

    async def test_connection(
        self, gateway_id: str, transport_type: str, connection_params: dict[str, Any]
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        await self._send_command(
            gateway_id,
            "command.gateway_test_connection",
            {"request_id": request_id, "transport_type": transport_type, "connection_params": connection_params},
        )
        result = await self._wait_for(request_id, TEST_CONNECTION_TIMEOUT_SECONDS)
        return result or {"request_id": request_id, "ok": False, "error": "sin respuesta del gateway"}

    async def handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type")
        if event_type not in ("gateway.devices_found", "gateway.test_connection_result"):
            return
        payload = event.get("payload") or {}
        future = self._waiters.get(payload.get("request_id"))
        if future is not None and not future.done():
            future.set_result(payload)

    async def _wait_for(self, request_id: str, timeout: float) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._waiters[request_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiters.pop(request_id, None)

    # ── Configuración (CRUD) ────────────────────────────────────────────────

    async def configure(
        self,
        gateway_id: str,
        name: str,
        transport_type: str,
        connection_params: dict[str, Any],
        enabled: bool = True,
        priority: int = 0,
    ) -> GatewayInfo:
        """Guarda la configuración (wizard "Guardar" o importación) y reconecta
        con los parámetros definitivos — incluso si una prueba previa ya dejó
        una conexión activa: una reconexión de más es aceptable a cambio de no
        duplicar el camino de conexión (ADR 0021 §3)."""
        async with self._session_factory() as session, session.begin():
            info = await SqlGatewayRepository(session).configure(
                gateway_id,
                name,
                transport_type,
                connection_params,
                enabled,
                priority,
                desired_status="connected" if enabled else "disconnected",
            )
        if enabled:
            await self._send_command(
                gateway_id,
                "command.gateway_connect",
                {"transport_type": transport_type, "connection_params": connection_params},
            )
        return info

    async def import_legacy(self, gateway_id: str) -> GatewayInfo | None:
        """Compatibilidad `.env` (ADR 0021 §7): reclama una fila nacida solo de
        heartbeat, usando su transporte/actual como valor inicial best-effort.
        Ya está conectada (viene del heartbeat): no hace falta comando."""
        existing = await self.get(gateway_id)
        if existing is None:
            return None
        async with self._session_factory() as session, session.begin():
            return await SqlGatewayRepository(session).configure(
                gateway_id,
                existing.name or gateway_id,
                existing.transport_type or existing.transport,
                {},
                enabled=True,
                priority=0,
                desired_status="connected",
            )

    async def update(
        self,
        gateway_id: str,
        name: str | None = None,
        transport_type: str | None = None,
        connection_params: dict[str, Any] | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
    ) -> GatewayInfo | None:
        desired_status = "connected" if enabled is True else "disconnected" if enabled is False else None
        async with self._session_factory() as session, session.begin():
            info = await SqlGatewayRepository(session).update_config(
                gateway_id, name, transport_type, connection_params, enabled, priority, desired_status
            )
        if info is None:
            return None
        if enabled is False:
            await self._send_command(gateway_id, "command.gateway_disconnect", {})
        elif info.enabled and (enabled is True or transport_type is not None or connection_params is not None):
            await self._send_command(
                gateway_id,
                "command.gateway_connect",
                {"transport_type": info.transport_type, "connection_params": info.connection_params},
            )
        return info

    async def connect(self, gateway_id: str) -> GatewayInfo | None:
        async with self._session_factory() as session, session.begin():
            info = await SqlGatewayRepository(session).set_desired_status(gateway_id, "connected")
        if info is not None:
            await self._send_command(
                gateway_id,
                "command.gateway_connect",
                {"transport_type": info.transport_type, "connection_params": info.connection_params},
            )
        return info

    async def disconnect(self, gateway_id: str) -> GatewayInfo | None:
        async with self._session_factory() as session, session.begin():
            info = await SqlGatewayRepository(session).set_desired_status(gateway_id, "disconnected")
        if info is not None:
            await self._send_command(gateway_id, "command.gateway_disconnect", {})
        return info

    async def delete(self, gateway_id: str) -> bool:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session, session.begin():
            deleted = await SqlGatewayRepository(session).soft_delete(gateway_id, now)
        if deleted:
            await self._send_command(gateway_id, "command.gateway_disconnect", {})
        return deleted

    # ── Reconciliación (ADR 0021 §5): invocado desde IngestService ──────────

    async def reconcile_after_heartbeat(self, info: GatewayInfo) -> None:
        if info.managed and info.desired_status == "connected" and info.enabled:
            await self._send_command(
                info.gateway_id,
                "command.gateway_connect",
                {"transport_type": info.transport_type, "connection_params": info.connection_params},
            )

    async def _send_command(self, gateway_id: str, command_type: str, payload: dict[str, Any]) -> None:
        await self._queue.enqueue(gateway_id, make_command_envelope(command_type, payload))
