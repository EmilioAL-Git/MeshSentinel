"""Fuente MQTT de solo ingesta (ADR 0032).

Se suscribe a un broker (público o propio) donde las pasarelas Meshtastic
suben sus ServiceEnvelope, descifra los canales cuya clave conocemos y mete
los paquetes en el MISMO pipeline que un nodo conectado: se decodifican con la
librería oficial (una `MeshInterface` sin dispositivo hace de decodificador) y
salen por el decoder v1 de siempre. Nunca transmite: no hay radio.

Hereda de `MeshtasticStreamTransport` para reutilizar ciclo de vida, backoff,
bomba de eventos y contadores (ADR 0023: sin forks de comportamiento); solo
cambian CÓMO llegan los paquetes y que toda operación de escritura se rechaza.
"""

import base64
import logging
import ssl
import threading
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from meshtastic.mesh_interface import MeshInterface
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2
from google.protobuf.message import DecodeError
from pubsub import pub

from gateway.config import Settings
from gateway.transports.base import EmitFn
from gateway.transports.meshtastic_stream import MeshtasticStreamTransport

logger = logging.getLogger("gateway.transport")

# Clave por defecto de Meshtastic ("AQ=="): se deriva sumando (b - 1) al último byte
_DEFAULT_KEY = bytes(
    [0xD4, 0xF1, 0xBB, 0x3A, 0x20, 0x29, 0x07, 0x59, 0xF0, 0xBC, 0xFF, 0xAB, 0xCF, 0x4E, 0x69, 0x01]
)


_MAX_NODE_CACHE = 20_000


def expand_psk(psk_b64: str) -> bytes | None:
    """PSK base64 → clave AES (16/32 bytes). 1 byte = clave por defecto
    desplazada; vacío = canal sin cifrar (None)."""
    try:
        raw = base64.b64decode(psk_b64) if psk_b64 else b""
    except Exception:
        return None
    if len(raw) == 0:
        return None
    if len(raw) == 1:
        return _DEFAULT_KEY[:-1] + bytes([(_DEFAULT_KEY[-1] + raw[0] - 1) & 0xFF])
    if len(raw) in (16, 32):
        return raw
    return None


def decrypt_payload(key: bytes, packet_id: int, from_num: int, data: bytes) -> bytes:
    # Nonce de Meshtastic: id (u64 LE) + nodo origen (u32 LE) + 4 bytes a cero
    nonce = packet_id.to_bytes(8, "little") + from_num.to_bytes(4, "little") + bytes(4)
    decryptor = Cipher(algorithms.AES(key), modes.CTR(nonce)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def inside_bbox(lat: float, lon: float, bbox: list[float]) -> bool:
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east


class MqttDecoderInterface(MeshInterface):
    """MeshInterface sin dispositivo: solo decodifica MeshPacket → dict y los
    publica por PyPubSub, igual que haría con un nodo real."""

    def __init__(self) -> None:
        MeshInterface.__init__(self, noProto=True)
        self.isConnected.set()
        self.client: Any = None
        # Sin _startConfig() la librería deja estas tablas en None y revienta
        # al resolver nodos; aquí hacen de caché id↔num de lo que se va oyendo
        self.nodes = {}
        self.nodesByNum = {}
        self.myInfo = None

    def _sendToRadioImpl(self, toRadio: Any) -> None:  # noqa: ARG002
        raise ConnectionError("fuente MQTT: solo lectura, no hay radio")

    def close(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                logger.debug("mqtt.close_error", exc_info=True)


class MqttIngestTransport(MeshtasticStreamTransport):
    name = "mqtt"

    def __init__(self, emit: EmitFn, settings: Settings) -> None:
        if not settings.mqtt_host:
            raise ValueError("MQTT transport requires a host (GATEWAY_MQTT_HOST / connection_params.host)")
        if settings.mqtt_geo_bbox and len(settings.mqtt_geo_bbox) != 4:
            raise ValueError("mqtt geo_bbox debe ser [sur, oeste, norte, este]")
        super().__init__(emit, settings)
        self.tx_enabled = False  # sin radio: por definición solo recepción
        self._keys: dict[str, bytes | None] = {
            name: expand_psk(psk) for name, psk in settings.mqtt_channel_keys.items()
        }
        self._default_key = expand_psk(settings.mqtt_psk)
        self._outside: set[str] = set()

    # ── Conexión ─────────────────────────────────────────────────────────────

    def _connect_blocking(self) -> Any:
        import paho.mqtt.client as mqtt

        s = self._settings
        iface = MqttDecoderInterface()
        ready = threading.Event()
        failure: list[str] = []

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if s.mqtt_username:
            client.username_pw_set(s.mqtt_username, s.mqtt_password or None)
        if s.mqtt_tls:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        def on_connect(c: Any, _u: Any, _f: Any, reason_code: Any, _p: Any = None) -> None:
            if reason_code.is_failure:
                failure.append(str(reason_code))
                ready.set()
                return
            c.subscribe(s.mqtt_topic)
            ready.set()

        def on_disconnect(c: Any, *_a: Any) -> None:
            # Sin reconexión automática de paho: la reconexión es del transporte
            # (backoff, snapshot, estado emitido) igual que en USB/TCP.
            c.disconnect()
            iface.isConnected.clear()
            pub.sendMessage("meshtastic.connection.lost", interface=iface)

        def on_message(_c: Any, _u: Any, msg: Any) -> None:
            try:
                self._handle_message(iface, msg.topic, msg.payload)
            except Exception:
                self._counters["decode_errors"] += 1
                logger.debug("mqtt.message_error topic=%s", msg.topic, exc_info=True)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        iface.client = client
        try:
            client.connect(s.mqtt_host, s.mqtt_port, keepalive=30)
            client.loop_start()
            if not ready.wait(s.connect_timeout):
                raise ConnectionError(f"timeout conectando al broker {s.mqtt_host}:{s.mqtt_port}")
            if failure:
                raise ConnectionError(f"broker rechazó la conexión: {failure[0]}")
        except Exception:
            iface.close()
            raise
        return iface

    def _endpoint_description(self) -> str:
        return f"{self._settings.mqtt_host}:{self._settings.mqtt_port}"

    # ── Paquetes ─────────────────────────────────────────────────────────────

    def _handle_message(self, iface: MqttDecoderInterface, topic: str, payload: bytes) -> None:
        self.mark_device_response()  # el broker entrega: la fuente está viva
        # Convención de Meshtastic: ServiceEnvelope en `<root>/2/e/<canal>/<gw>`.
        # Cualquier otro tema (json, map, stat, formatos ajenos de brokers
        # públicos) no es un envelope y se descarta sin ruido.
        if "/e/" not in topic:
            self._counters["skipped_topic"] += 1
            return
        env = mqtt_pb2.ServiceEnvelope()
        try:
            env.ParseFromString(payload)
        except DecodeError:
            self._counters["bad_envelope"] += 1
            return
        packet = env.packet
        if packet.WhichOneof("payload_variant") == "encrypted":
            key = self._keys.get(env.channel_id, self._default_key)
            if key is None:
                self._counters["undecryptable"] += 1
                return
            try:
                plain = decrypt_payload(key, packet.id, getattr(packet, "from"), packet.encrypted)
                data = mesh_pb2.Data()
                data.ParseFromString(plain)
                portnums_pb2.PortNum.Name(data.portnum)  # clave errónea → portnum basura
            except Exception:
                self._counters["undecryptable"] += 1
                return
            packet.decoded.CopyFrom(data)
        if not packet.rx_time:
            packet.rx_time = int(time.time())
        if len(iface.nodesByNum) > _MAX_NODE_CACHE:  # feed público: acotar la caché
            iface.nodes.clear()
            iface.nodesByNum.clear()
        iface._handlePacketFromRadio(packet)

    async def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        bbox = self._settings.mqtt_geo_bbox
        node_id = payload.get("node_id")
        if bbox and node_id:
            if event_type == "position.updated":
                lat, lon = payload.get("latitude"), payload.get("longitude")
                if lat is not None and lon is not None:
                    if not inside_bbox(float(lat), float(lon), bbox):
                        self._outside.add(node_id)
                        self._counters["geo_dropped"] += 1
                        return
                    self._outside.discard(node_id)
            if node_id in self._outside:
                self._counters["geo_dropped"] += 1
                return
        await super()._publish(event_type, payload)

    # ── Sin radio: nada de escritura, nada de snapshot de nodo local ─────────

    def _instrument(self, iface: Any) -> None:  # noqa: ARG002
        return

    async def probe(self) -> None:
        iface = self._iface
        client = getattr(iface, "client", None)
        if client is not None and client.is_connected():
            self.mark_device_response()

    def _read_tx_enabled(self) -> bool | None:
        return False  # sin radio: por definición solo recepción

    def _local_node_info(self) -> Any:
        return (None, None, None, None, None, [], {})

    async def send_command(self, command: dict[str, Any]) -> None:  # noqa: ARG002
        raise ConnectionError("fuente MQTT: solo lectura, no transmite")

    async def execute_admin(self, operation: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        raise ConnectionError("fuente MQTT: solo lectura, no admite administración")
