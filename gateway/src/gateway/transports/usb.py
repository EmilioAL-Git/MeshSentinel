"""Transporte USB sobre la librería oficial `meshtastic` (ADR 0009/0010).

La librería es síncrona: SerialInterface lanza un hilo lector y publica por
PyPubSub. Este módulo puentea esos callbacks (hilo) hacia asyncio mediante
call_soon_threadsafe + Queue, y gestiona reconexión con backoff exponencial.
"""

import asyncio
import logging
import random
from collections import Counter
from typing import Any

from pubsub import pub

from gateway.config import Settings
from gateway.decoder.meshtastic import decode_nodedb_entry, decode_packet
from gateway.transports.base import EmitFn, Transport

logger = logging.getLogger("gateway.usb")

# Centinela de cierre forzoso (close() del transporte): termina el pump siempre
_FORCE_DISCONNECT = object()


class MeshtasticUsbTransport(Transport):
    name = "usb"

    def __init__(self, emit: EmitFn, settings: Settings) -> None:
        super().__init__(emit)
        self._settings = settings
        self._closed = asyncio.Event()
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._iface: Any = None
        self._counters: Counter[str] = Counter()
        # Waiters de respuestas admin: (node_id, response_key) -> Future
        self._admin_waiters: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}

    # ── Callbacks PyPubSub: corren en el hilo lector de la librería ─────────
    # Nunca tocan Redis ni asyncio directamente; solo encolan thread-safe.

    def _enqueue(self, item: Any) -> None:
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except (RuntimeError, asyncio.QueueFull):
            self._counters["dropped"] += 1

    def _on_receive(self, packet: dict[str, Any], interface: Any) -> None:  # noqa: ARG002
        self._enqueue(("packet", packet))

    def _on_connection_lost(self, interface: Any) -> None:
        # OJO: iface.close() también dispara connection.lost (el hilo lector al
        # salir llama a _disconnected). El evento va etiquetado con SU interface
        # para que el pump ignore desconexiones de conexiones anteriores; sin
        # esto, cada reconexión tumbaba la conexión nueva en bucle perpetuo.
        logger.warning("usb.connection_lost device=%s", getattr(interface, "devPath", "?"))
        self._enqueue(("disconnect", interface))

    # ── Conexión (bloqueante, ejecutada con to_thread) ──────────────────────

    def _discover_device(self) -> str | None:
        if self._settings.usb_device:
            logger.info("usb.device_selected device=%s source=config", self._settings.usb_device)
            return self._settings.usb_device
        from meshtastic.util import findPorts

        ports = findPorts(eliminate_duplicates=True)
        logger.info("usb.autodetect candidates=%s", ports)
        if not ports:
            return None
        if len(ports) > 1:
            logger.warning("usb.autodetect multiple devices, using first: %s", ports)
        logger.info("usb.device_selected device=%s source=autodetect", ports[0])
        return ports[0]

    def _connect_blocking(self) -> Any:
        from meshtastic.serial_interface import SerialInterface

        device = self._discover_device()
        if device is None:
            raise ConnectionError("No Meshtastic USB device found (autodetect)")
        return SerialInterface(devPath=device)

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_connection_lost, "meshtastic.connection.lost")

        delay = self._settings.reconnect_initial_delay
        while not self._closed.is_set():
            self.status = "connecting"
            await self.emit_status()
            try:
                self._iface = await asyncio.to_thread(self._connect_blocking)
            except Exception as exc:
                self.status = "error"
                await self.emit_status(detail=f"connect failed: {exc}")
                logger.error("usb.connect_failed error=%r retry_in=%.0fs", exc, delay)
                await self._sleep(delay)
                delay = min(delay * 2, self._settings.reconnect_max_delay)
                continue

            delay = self._settings.reconnect_initial_delay  # conexión OK: backoff a cero
            await self._on_connected()
            await self._pump_events()  # hasta desconexión o cierre

            await asyncio.to_thread(self._close_iface)
            self._fail_pending_admin("connection lost during operation")
            self._drain_queue()  # descarta paquetes/eventos de la conexión muerta
            if not self._closed.is_set():
                self.status = "disconnected"
                await self.emit_status(detail="connection lost, reconnecting")
                await self._sleep(self._settings.reconnect_initial_delay)

    async def _on_connected(self) -> None:
        info = await asyncio.to_thread(self._local_node_info)
        self.local_node_id, nodes = info
        self.status = "connected"
        await self.emit_status()
        logger.info(
            "usb.connected device=%s local_node=%s nodedb_size=%d",
            getattr(self._iface, "devPath", "?"),
            self.local_node_id,
            len(nodes),
        )
        # Snapshot de la NodeDB del dispositivo: puebla el registry al instante.
        for node_id_raw, entry in nodes.items():
            decoded = decode_nodedb_entry(node_id_raw, entry)
            if decoded:
                await self._publish(*decoded)

    def _local_node_info(self) -> tuple[str | None, dict[str, Any]]:
        nodes = dict(getattr(self._iface, "nodes", None) or {})
        my_info = self._iface.getMyNodeInfo() or {}
        local_id = (my_info.get("user") or {}).get("id")
        return (local_id.lower() if isinstance(local_id, str) else None), nodes

    def _fail_pending_admin(self, reason: str) -> None:
        """Falla las operaciones admin en vuelo sin esperar su timeout completo."""
        for key, future in list(self._admin_waiters.items()):
            if not future.done():
                future.set_exception(ConnectionError(reason))
            self._admin_waiters.pop(key, None)

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def _pump_events(self) -> None:
        while not self._closed.is_set():
            item = await self._queue.get()
            if item is _FORCE_DISCONNECT:
                return
            kind, payload = item
            if kind == "disconnect":
                if payload is self._iface:
                    return
                logger.debug("usb.stale_disconnect ignored (previous interface)")
                self._counters["stale_disconnects"] += 1
                continue
            if kind != "packet":
                continue
            packet = payload
            if self._resolve_admin_response(packet):
                continue
            try:
                decoded = decode_packet(packet)
            except Exception:
                self._counters["decode_errors"] += 1
                logger.exception("usb.decode_error packet_id=%s", packet.get("id"))
                continue
            if decoded is None:
                self._counters["ignored"] += 1
                continue
            await self._publish(*decoded)

    async def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        await self._emit(event_type, payload)
        self._counters[event_type] += 1
        self._counters["total"] += 1
        logger.debug("usb.event_published type=%s node=%s", event_type, payload.get("node_id"))
        if self._counters["total"] % 100 == 0:
            self._log_counters()

    def _log_counters(self) -> None:
        stats = " ".join(f"{k}={v}" for k, v in sorted(self._counters.items()))
        logger.info("usb.stats %s", stats)

    async def _sleep(self, base: float) -> None:
        jitter = base * random.uniform(0.8, 1.2)
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=jitter)
        except asyncio.TimeoutError:
            pass

    def _close_iface(self) -> None:
        if self._iface is not None:
            try:
                self._iface.close()
            except Exception:
                logger.debug("usb.close_error", exc_info=True)
            self._iface = None

    # ── Administración remota (M1.1: solo GET) ──────────────────────────────

    def _resolve_admin_response(self, packet: dict[str, Any]) -> bool:
        decoded = packet.get("decoded")
        if not isinstance(decoded, dict) or decoded.get("portnum") != "ADMIN_APP":
            return False
        admin = decoded.get("admin")
        from_id = str(packet.get("fromId") or "").lower()
        if isinstance(admin, dict):
            self._counters["admin_responses"] += 1
            for key in admin:
                fut = self._admin_waiters.get((from_id, key))
                if fut is not None and not fut.done():
                    fut.set_result(admin)
                    logger.info("usb.admin_response node=%s key=%s", from_id, key)
        return True  # los paquetes ADMIN_APP no van al bus de telemetría

    def _send_admin_blocking(self, node_id: str, message: Any) -> None:
        # requestChannels=False: pedir canales al crear el Node remoto costaría
        # varios paquetes LoRa innecesarios para un GET
        node = self._iface.getNode(node_id, requestChannels=False)
        node._sendAdmin(message, wantResponse=True)

    async def execute_admin(self, operation: dict[str, Any]) -> dict[str, Any]:
        from gateway.decoder.admin import build_admin_request

        if self.status != "connected" or self._iface is None or self._loop is None:
            raise ConnectionError("USB transport not connected")
        # El enlace puede haberse caído sin que el pump lo haya procesado aún:
        # comprobar el estado real de la librería evita bloquear 30 s en
        # _waitConnected() y devuelve un error accionable (el backend reintenta)
        lib_connected = getattr(self._iface, "isConnected", None)
        if lib_connected is not None and not lib_connected.is_set():
            raise ConnectionError("USB link not ready (device disconnected or reconnecting)")
        node_id = str(operation["target_node_id"]).lower()
        message, response_key = build_admin_request(
            operation["operation_type"], operation.get("params") or {}
        )
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._admin_waiters[(node_id, response_key)] = future
        try:
            await asyncio.to_thread(self._send_admin_blocking, node_id, message)
            logger.info(
                "usb.admin_sent op=%s type=%s node=%s",
                operation.get("operation_id"), operation["operation_type"], node_id,
            )
            admin = await future  # el timeout lo impone el CommandConsumer
            result = admin.get(response_key)
            return result if isinstance(result, dict) else {"value": result}
        finally:
            self._admin_waiters.pop((node_id, response_key), None)

    async def send_command(self, command: dict[str, Any]) -> None:
        logger.warning("usb.command_rejected type=%s (not supported)", command.get("command_type"))

    async def close(self) -> None:
        self._closed.set()
        self._enqueue(_FORCE_DISCONNECT)  # desbloquea _pump_events si estaba esperando
        await asyncio.to_thread(self._close_iface)
        self.status = "disconnected"
        await self.emit_status(detail="shutdown")
        self._log_counters()
