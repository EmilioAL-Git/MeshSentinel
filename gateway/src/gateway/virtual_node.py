"""Nodo virtual (ADR 0033): un servidor TCP que habla el protocolo de stream de
Meshtastic (cabecera 0x94 0xC3 + longitud + protobuf) y deja que la app móvil,
el CLI de Python u otro cliente se conecten A TRAVÉS de la pasarela en lugar
de directamente al nodo — que solo admite un cliente a la vez y ya lo ocupa
la pasarela.

La pasarela sigue siendo la única que habla con el nodo real:
  · lo que el nodo emite (paquetes, node_info) se difunde a los clientes;
  · la configuración inicial (want_config_id) se sirve desde el estado que la
    librería ya tiene del nodo (myInfo, NodeDB, canales, config), sin molestar
    al nodo;
  · lo que envía el cliente se reenvía al nodo, salvo lo bloqueado por
    seguridad (administración, salvo que se permita expresamente).

Solo contiene lógica de protocolo; no conoce Redis ni el backend. Importa la
librería `meshtastic` (solo protobufs), igual que `transports/` y `decoder/`.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from google.protobuf import json_format
from meshtastic.protobuf import admin_pb2, config_pb2, mesh_pb2, module_config_pb2, portnums_pb2

logger = logging.getLogger("gateway.virtual_node")

START1, START2 = 0x94, 0xC3
MAX_FRAME = 512
_CONFIG_COOLDOWN_SECONDS = 5.0  # mismo want_config_id repetido: bucle de reconexión del cliente
_MAX_WRITE_BUFFER = 1_000_000  # cliente lento: se le expulsa antes de acumular memoria
_BROADCAST_VARIANTS = frozenset({"packet", "node_info", "clientNotification"})


def frame(payload: bytes) -> bytes:
    return bytes([START1, START2, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload


class FrameParser:
    """Extrae tramas de un flujo. Re-sincroniza ante basura: el cliente Python
    manda 32 bytes 0xC3 al conectar para despertar al dispositivo."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        out: list[bytes] = []
        while True:
            start = self._find_start()
            if start < 0:
                # descarta todo salvo un posible START1 final a medio llegar
                self._buf = self._buf[-1:] if self._buf and self._buf[-1] == START1 else bytearray()
                return out
            if start:
                del self._buf[:start]
            if len(self._buf) < 4:
                return out
            length = (self._buf[2] << 8) | self._buf[3]
            if length > MAX_FRAME:
                del self._buf[:2]  # cabecera falsa: seguir buscando
                continue
            if len(self._buf) < 4 + length:
                return out
            out.append(bytes(self._buf[4 : 4 + length]))
            del self._buf[: 4 + length]

    def _find_start(self) -> int:
        for i in range(len(self._buf) - 1):
            if self._buf[i] == START1 and self._buf[i + 1] == START2:
                return i
        return -1


@dataclass(slots=True)
class _Client:
    client_id: str
    writer: asyncio.StreamWriter
    peer: str
    configured: bool = False
    last_config_id: int | None = None
    last_config_at: float = 0.0
    last_rx: float = field(default_factory=time.monotonic)
    from_radio_id: int = 0


SendToRadio = Callable[[Any], Awaitable[None]]


class VirtualNodeServer:
    def __init__(
        self,
        *,
        port: int,
        allow_admin: bool,
        get_iface: Callable[[], Any],
        send_to_radio: SendToRadio,
        host: str = "0.0.0.0",  # noqa: S104 - el punto de la función es ser alcanzable desde la LAN
        idle_timeout: float = 900.0,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.port = port
        self.allow_admin = allow_admin
        self._host = host
        self._get_iface = get_iface
        self._send_to_radio = send_to_radio
        self._idle_timeout = idle_timeout
        self._on_change = on_change
        self._server: asyncio.AbstractServer | None = None
        self._clients: dict[str, _Client] = {}
        self._next_id = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reaper: asyncio.Task[None] | None = None
        self.blocked = 0

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._server = await asyncio.start_server(self._on_client, self._host, self.port)
        self._reaper = asyncio.create_task(self._reap_idle(), name="virtual-node-reaper")
        logger.info("virtual_node.listening port=%d allow_admin=%s", self.port, self.allow_admin)

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            await asyncio.gather(self._reaper, return_exceptions=True)
            self._reaper = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for client in list(self._clients.values()):
            self._drop(client)

    def _notify(self) -> None:
        """Avisa de que cambió el nº de clientes (para refrescar el estado sin esperar al latido)."""
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                logger.debug("virtual_node.on_change_failed", exc_info=True)

    def status(self) -> dict[str, Any]:
        return {"port": self.port, "clients": len(self._clients), "allow_admin": self.allow_admin}

    # ── Del nodo hacia los clientes ──────────────────────────────────────────

    def feed(self, raw: bytes) -> None:
        """FromRadio crudo recién recibido del nodo. Seguro desde el hilo lector
        de la librería: solo encola en el bucle asyncio."""
        if self._loop is not None and self._clients:
            self._loop.call_soon_threadsafe(self._broadcast, raw)

    def _broadcast(self, raw: bytes) -> None:
        try:
            msg = mesh_pb2.FromRadio()
            msg.ParseFromString(raw)
        except Exception:
            return
        if msg.WhichOneof("payload_variant") not in _BROADCAST_VARIANTS:
            return
        data = frame(raw)
        for client in list(self._clients.values()):
            if client.configured:
                self._write(client, data)

    def _write(self, client: _Client, data: bytes) -> None:
        transport = client.writer.transport
        if transport.is_closing():
            return
        if transport.get_write_buffer_size() > _MAX_WRITE_BUFFER:
            logger.warning("virtual_node.slow_client_dropped client=%s", client.client_id)
            self._drop(client)
            return
        client.writer.write(data)

    # ── De los clientes hacia el nodo ────────────────────────────────────────

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._next_id += 1
        peername = writer.get_extra_info("peername")
        peer = f"{peername[0]}:{peername[1]}" if peername else "?"
        client = _Client(client_id=f"vn-{self._next_id}", writer=writer, peer=peer)
        self._clients[client.client_id] = client
        self._notify()
        logger.info("virtual_node.client_connected client=%s peer=%s total=%d", client.client_id, peer, len(self._clients))
        parser = FrameParser()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                client.last_rx = time.monotonic()
                for payload in parser.feed(data):
                    await self._handle_to_radio(client, payload)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("virtual_node.client_error client=%s", client.client_id)
        finally:
            self._drop(client)

    def _drop(self, client: _Client) -> None:
        if self._clients.pop(client.client_id, None) is not None:
            logger.info("virtual_node.client_disconnected client=%s total=%d", client.client_id, len(self._clients))
            self._notify()
        try:
            client.writer.close()
        except Exception:
            pass

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            for client in list(self._clients.values()):
                if now - client.last_rx > self._idle_timeout:
                    logger.info("virtual_node.idle_client_dropped client=%s", client.client_id)
                    self._drop(client)

    async def _handle_to_radio(self, client: _Client, payload: bytes) -> None:
        try:
            msg = mesh_pb2.ToRadio()
            msg.ParseFromString(payload)
        except Exception:
            logger.debug("virtual_node.bad_toradio client=%s", client.client_id)
            return
        variant = msg.WhichOneof("payload_variant")
        if variant == "want_config_id":
            await self._send_initial_config(client, msg.want_config_id)
        elif variant == "heartbeat":
            # Respuesta local: los clientes esperan una trama para dar el enlace por vivo
            reply = mesh_pb2.FromRadio(queueStatus=mesh_pb2.QueueStatus(res=0, free=32, maxlen=32))
            self._send_from_radio(client, reply)
        elif variant == "disconnect":
            self._drop(client)
        elif variant == "packet":
            if self._is_blocked(msg.packet):
                self.blocked += 1
                logger.warning("virtual_node.blocked client=%s portnum=%s", client.client_id, msg.packet.decoded.portnum)
                return
            await self._send_to_radio(msg)
        elif variant == "mqttClientProxyMessage":
            await self._send_to_radio(msg)
        else:
            # xmodemPacket (ficheros del dispositivo) y desconocidos: nunca
            self.blocked += 1
            logger.warning("virtual_node.blocked client=%s variant=%s", client.client_id, variant)

    def _is_blocked(self, packet: Any) -> bool:
        if packet.WhichOneof("payload_variant") == "encrypted":
            return not self.allow_admin  # no inspeccionable: podría ser administración PKC
        if packet.decoded.portnum != portnums_pb2.PortNum.ADMIN_APP:
            return False
        if not self.allow_admin:
            return True
        try:
            admin = admin_pb2.AdminMessage()
            admin.ParseFromString(packet.decoded.payload)
        except Exception:
            return True  # administración ilegible: por seguridad, no
        # add_contact desde un cliente corrompería las claves PKI del nodo
        return admin.WhichOneof("payload_variant") == "add_contact"

    # ── Configuración inicial servida desde la caché de la librería ──────────

    def _send_from_radio(self, client: _Client, msg: Any) -> None:
        client.from_radio_id += 1
        msg.id = client.from_radio_id
        self._write(client, frame(msg.SerializeToString()))

    def build_config_frames(self, iface: Any) -> list[Any]:
        """FromRadio de la configuración del nodo, en el orden del firmware."""
        frames: list[Any] = []
        if getattr(iface, "myInfo", None) is not None:
            frames.append(mesh_pb2.FromRadio(my_info=iface.myInfo))
        if getattr(iface, "metadata", None) is not None:
            frames.append(mesh_pb2.FromRadio(metadata=iface.metadata))
        for node in list((getattr(iface, "nodesByNum", None) or {}).values()):
            info = mesh_pb2.NodeInfo()
            try:
                json_format.ParseDict(node, info, ignore_unknown_fields=True)
            except Exception:
                continue
            frames.append(mesh_pb2.FromRadio(node_info=info))
        local = getattr(iface, "localNode", None)
        for channel in list(getattr(local, "channels", None) or []):
            frames.append(mesh_pb2.FromRadio(channel=channel))
        local_config = getattr(local, "localConfig", None)
        if local_config is not None:
            variants = {f.name for f in config_pb2.Config.DESCRIPTOR.oneofs_by_name["payload_variant"].fields}
            for field_desc in local_config.DESCRIPTOR.fields:
                if field_desc.name in variants and local_config.HasField(field_desc.name):
                    cfg = config_pb2.Config()
                    getattr(cfg, field_desc.name).CopyFrom(getattr(local_config, field_desc.name))
                    frames.append(mesh_pb2.FromRadio(config=cfg))
        module_config = getattr(local, "moduleConfig", None)
        if module_config is not None:
            variants = {f.name for f in module_config_pb2.ModuleConfig.DESCRIPTOR.oneofs_by_name["payload_variant"].fields}
            for field_desc in module_config.DESCRIPTOR.fields:
                if field_desc.name in variants and module_config.HasField(field_desc.name):
                    mcfg = module_config_pb2.ModuleConfig()
                    getattr(mcfg, field_desc.name).CopyFrom(getattr(module_config, field_desc.name))
                    frames.append(mesh_pb2.FromRadio(moduleConfig=mcfg))
        return frames

    async def _send_initial_config(self, client: _Client, config_id: int) -> None:
        now = time.monotonic()
        if client.last_config_id == config_id and now - client.last_config_at < _CONFIG_COOLDOWN_SECONDS:
            logger.warning("virtual_node.duplicate_config_ignored client=%s id=%s", client.client_id, config_id)
            return
        iface = self._get_iface()
        if iface is None or getattr(iface, "myInfo", None) is None:
            # El enlace con el nodo no está listo: cerrar para que el cliente reintente
            logger.info("virtual_node.config_unavailable client=%s", client.client_id)
            self._drop(client)
            return
        client.last_config_id, client.last_config_at = config_id, now
        for i, msg in enumerate(self.build_config_frames(iface), start=1):
            self._send_from_radio(client, msg)
            if i % 50 == 0:
                await client.writer.drain()
        self._send_from_radio(client, mesh_pb2.FromRadio(config_complete_id=config_id))
        await client.writer.drain()
        client.configured = True
        logger.info("virtual_node.config_sent client=%s id=%s", client.client_id, config_id)
