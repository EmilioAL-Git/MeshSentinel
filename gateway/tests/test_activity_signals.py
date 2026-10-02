"""Las tres señales de actividad son independientes: nodo responde, RX y TX LoRa."""

import asyncio
from types import SimpleNamespace

from gateway.config import Settings
from gateway.transports.tcp import MeshtasticTcpTransport


class FakeIface:
    def __init__(self) -> None:
        self.rx_frames = 0
        self.sent = 0
        self.heartbeats = 0

    def _handleFromRadio(self, data):  # noqa: N802
        self.rx_frames += 1

    def _sendPacket(self, *a, **kw):  # noqa: N802
        self.sent += 1
        return "p"

    def sendHeartbeat(self):  # noqa: N802
        self.heartbeats += 1


async def _noop(*_a, **_k):
    return None


def _transport() -> MeshtasticTcpTransport:
    return MeshtasticTcpTransport(_noop, Settings(transport="tcp", tcp_host="127.0.0.1"))


def test_instrument_stamps_device_response_and_tx_but_not_rx():
    t = _transport()
    iface = FakeIface()
    t._instrument(iface)
    assert (t.last_device_response_at, t.last_lora_tx_at, t.last_lora_rx_at) == (None, None, None)

    iface._handleFromRadio(b"x")  # el nodo habla por el enlace API
    assert iface.rx_frames == 1
    assert t.last_device_response_at is not None
    assert t.last_lora_rx_at is None  # una trama del nodo NO es tráfico LoRa

    iface._sendPacket("pkt")
    assert iface.sent == 1 and t.last_lora_tx_at is not None


def test_lora_rx_ignores_packets_from_the_local_node():
    t = _transport()
    t._local_node_num = 0xAABBCCDD
    t._on_receive({"from": 0xAABBCCDD}, SimpleNamespace())  # telemetría propia vía API
    assert t.last_lora_rx_at is None
    t._on_receive({"from": 0x11223344}, SimpleNamespace())  # otro nodo, por radio
    assert t.last_lora_rx_at is not None


def test_probe_sends_heartbeat_and_status_carries_stamps():
    t = _transport()
    t._iface = FakeIface()
    t.status = "connected"
    sent = []

    async def emit(event_type, payload):
        sent.append((event_type, payload))

    t._emit = emit

    async def go():
        await t.probe()
        t.mark_device_response()
        await t.emit_status()

    asyncio.run(go())
    assert t._iface.heartbeats == 1
    payload = sent[-1][1]
    assert payload["last_device_response_at"] and payload["last_lora_rx_at"] is None
