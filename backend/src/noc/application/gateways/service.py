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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.gateways.launcher_client import (
    GatewayLauncherClient,
    LauncherContainerNotFound,
    LauncherError,
)
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.nexus_repositories import SqlNexusOperationRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.application.dashboard import is_stale
from noc.application.envelopes import make_command_envelope
from noc.domain.nodes.entities import GatewayInfo

logger = logging.getLogger("noc.gateways")

DISCOVER_TIMEOUT_SECONDS = 15.0
TEST_CONNECTION_TIMEOUT_SECONDS = 30.0


class GatewayHasActiveWorkError(Exception):
    """El borrado de gateways ahora es real (pedido explícito del usuario:
    "comprueba antes de borrar si hay algún proceso o trabajo ejecutándose
    por si acaso") — sin esto, borrar una pasarela con una operación
    admin/Nexus en vuelo la dejaría huérfana (referencia a un gateway_id
    que ya no existe, sin nadie que la reclame)."""


class GatewayStillConnectedError(Exception):
    """Comprobación de vida del propio proceso, pedida aparte del trabajo
    en vuelo: solo bloquea si hay una conexión REAL activa (status
    "connected" — USB/TCP con nodo local), nunca un transporte "idle" (tras
    un disconnect(), sigue latiendo pero sin conexión real — reseteo limpio
    al borrar es el comportamiento buscado) ni uno "connecting"/
    "reconnecting"/"error"/"disconnected"/"unassigned"."""


class GatewayAlreadyExistsError(Exception):
    """`provision()`: ya hay una fila configurada (`managed=True`) con ese
    gateway_id — crear un contenedor nuevo nunca reconfigura un enlace
    existente, para eso está "Editar" en su propio panel."""


class VirtualNodeConfigError(Exception):
    """Puerto de nodo virtual inválido o ya en uso por otra pasarela (ADR 0033)."""


class LauncherUnavailableError(Exception):
    """`gateway-launcher` (ADR 0028) no respondió o rechazó la operación —
    la fila en BD no se toca: ni se crea al provisionar, ni se borra al
    eliminar una pasarela `container_managed` (evita un contenedor huérfano
    sin fila que lo represente, o una fila sin contenedor real detrás)."""


class GatewayService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        command_queue: RedisCommandQueue,
        stale_after_seconds: int = 90,
        launcher: GatewayLauncherClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._queue = command_queue
        self._stale_after_seconds = stale_after_seconds
        self._launcher = launcher
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

    # ── Lanzador de contenedores (ADR 0028) ──────────────────────────────────

    async def list_launcher_devices(self) -> list[dict[str, Any]]:
        """Dispositivos USB visibles en el host, vía gateway-launcher — para
        el paso 1 del asistente "Crear un contenedor nuevo", antes de que
        exista ningún gateway_id/proceso. Distinto de `discover()` (que
        correlaciona con un proceso YA vivo, para reconfigurar uno
        existente)."""
        if self._launcher is None:
            raise LauncherUnavailableError("gateway-launcher no está configurado en este despliegue")
        try:
            return await self._launcher.list_devices()
        except LauncherError as exc:
            raise LauncherUnavailableError(str(exc)) from exc

    async def provision(
        self,
        gateway_id: str,
        name: str,
        transport_type: str,
        connection_params: dict[str, Any],
    ) -> GatewayInfo:
        """"+ Añadir gateway" → "Crear un contenedor nuevo": pide al lanzador
        crear el contenedor YA con el transporte definitivo como variables de
        arranque (sin el baile idle→reconectar de los repuestos M6.3,
        retirados) y persiste la fila como container_managed. Si ya existe
        una fila configurada con este gateway_id, se rechaza antes de tocar
        el lanzador — nunca se reconfigura un enlace existente por esta vía."""
        if self._launcher is None:
            raise LauncherUnavailableError("gateway-launcher no está configurado en este despliegue")
        await self.check_virtual_node(gateway_id, connection_params)
        existing = await self.get(gateway_id)
        if existing is not None and existing.managed:
            raise GatewayAlreadyExistsError(f"«{gateway_id}» ya está configurado — elige otro identificador")
        try:
            await self._launcher.create_container(gateway_id, transport_type, connection_params)
        except LauncherError as exc:
            raise LauncherUnavailableError(str(exc)) from exc
        async with self._session_factory() as session, session.begin():
            return await SqlGatewayRepository(session).configure(
                gateway_id,
                name,
                transport_type,
                connection_params,
                enabled=True,
                priority=0,
                desired_status="connected",
                container_managed=True,
            )

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
        await self.check_virtual_node(gateway_id, connection_params)
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

    async def check_virtual_node(self, gateway_id: str, params: dict[str, Any]) -> None:
        """ADR 0033: el puerto del nodo virtual debe ser válido y no estar en
        uso por otra pasarela (cada una lo publica en el host)."""
        if not params.get("vn_enabled"):
            return
        port = params.get("vn_port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            raise VirtualNodeConfigError("El puerto del nodo virtual debe ser un número entre 1024 y 65535")
        async with self._session_factory() as session:
            others = await SqlGatewayRepository(session).list_all()
        for other in others:
            if other.gateway_id == gateway_id:
                continue
            if other.connection_params.get("vn_enabled") and other.connection_params.get("vn_port") == port:
                raise VirtualNodeConfigError(
                    f"El puerto {port} ya lo usa el nodo virtual de «{other.name or other.gateway_id}»"
                )

    @staticmethod
    def _vn_publish_signature(params: dict[str, Any] | None) -> tuple[bool, Any]:
        params = params or {}
        enabled = bool(params.get("vn_enabled"))
        return (enabled, params.get("vn_port") if enabled else None)

    async def update(
        self,
        gateway_id: str,
        name: str | None = None,
        transport_type: str | None = None,
        connection_params: dict[str, Any] | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
    ) -> GatewayInfo | None:
        if connection_params is not None:
            await self.check_virtual_node(gateway_id, connection_params)
            before = await self.get(gateway_id)
            # El puerto publicado es del CONTENEDOR (no se puede cambiar en
            # caliente): activar/desactivar o mover el puerto lo recrea.
            if (
                before is not None
                and before.container_managed
                and self._launcher is not None
                and self._vn_publish_signature(before.connection_params)
                != self._vn_publish_signature(connection_params)
            ):
                try:
                    await self._launcher.create_container(
                        gateway_id, transport_type or before.transport_type or "tcp", connection_params
                    )
                except LauncherError as exc:
                    raise LauncherUnavailableError(str(exc)) from exc
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

    async def resync(self, gateway_id: str) -> GatewayInfo | None:
        """Pide al proceso gateway que relea el nodo local y republique el
        snapshot de su NodeDB sin cortar el enlace (ADR 0032)."""
        async with self._session_factory() as session:
            info = await SqlGatewayRepository(session).get(gateway_id)
        if info is not None:
            await self._send_command(gateway_id, "command.gateway_resync", {})
        return info

    async def set_receive_only(self, gateway_id: str, receive_only: bool) -> GatewayInfo | None:
        async with self._session_factory() as session, session.begin():
            return await SqlGatewayRepository(session).set_receive_only(gateway_id, receive_only)

    async def set_primary(self, gateway_id: str, primary: bool) -> GatewayInfo | None:
        async with self._session_factory() as session, session.begin():
            return await SqlGatewayRepository(session).set_primary(gateway_id, primary)

    async def reorder(self, gateway_ids: list[str]) -> None:
        async with self._session_factory() as session, session.begin():
            await SqlGatewayRepository(session).reorder(gateway_ids)

    async def disconnect(self, gateway_id: str) -> GatewayInfo | None:
        async with self._session_factory() as session, session.begin():
            info = await SqlGatewayRepository(session).set_desired_status(gateway_id, "disconnected")
        if info is not None:
            await self._send_command(gateway_id, "command.gateway_disconnect", {})
        return info

    async def delete(self, gateway_id: str) -> bool:
        async with self._session_factory() as session, session.begin():
            repo = SqlGatewayRepository(session)
            info = await repo.get(gateway_id)
            # "connected" por sí solo no basta: un proceso muerto deja el
            # último status congelado para siempre (nadie vuelve a
            # heartbearlo) — sin comprobar frescura, una pasarela ya
            # abandonada bloquearía su propio borrado indefinidamente.
            if (
                info is not None
                and info.status == "connected"
                and not is_stale(info.updated_at, self._stale_after_seconds)
            ):
                raise GatewayStillConnectedError(
                    f"«{gateway_id}» sigue conectado de verdad — desconéctalo antes de eliminarlo"
                )
            if await SqlAdminOperationRepository(session).has_active_for_gateway(
                gateway_id
            ) or await SqlNexusOperationRepository(session).has_active_for_gateway(gateway_id):
                raise GatewayHasActiveWorkError(
                    f"«{gateway_id}» tiene operaciones pendientes o en vuelo — espera a que "
                    "terminen (o cancélalas) antes de eliminarla"
                )
            # ADR 0028: si el contenedor lo creó el lanzador, se destruye
            # ANTES de borrar la fila — si el lanzador falla, se aborta todo
            # (ni fila borrada ni comando enviado) para no dejar un
            # contenedor huérfano sin fila que lo represente.
            if info is not None and info.container_managed and self._launcher is not None:
                try:
                    await self._launcher.destroy_container(gateway_id)
                except LauncherContainerNotFound:
                    pass  # ya no existe: idempotente, seguimos con el borrado
                except LauncherError as exc:
                    raise LauncherUnavailableError(str(exc)) from exc
            deleted = await repo.delete(gateway_id)
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
