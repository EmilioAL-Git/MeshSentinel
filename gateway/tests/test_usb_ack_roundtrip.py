"""Regresión: `_ack_roundtrip` confundía un ACK implícito (generado
localmente cuando se agota el límite de reintentos del radio, sin
confirmación real del destino) con un ACK confirmado, porque solo miraba
`errorReason == "NONE"`. La propia librería oficial distingue ambos casos
comparando `packet["from"]` contra el nodo local (`Node.onAckNak`). Bug
detectado en producción: favoritos remotos se aplicaban correctamente,
ignorados remotos se marcaban "Confirmado" sin aplicarse de verdad en el
firmware."""

import asyncio

from gateway.config import Settings
from gateway.transports.usb import MeshtasticUsbTransport

LOCAL_NODE_NUM = 0xA1B2C3D4
REMOTE_NODE_NUM = 0xB2A7C3A8


class FakeLocalNode:
    nodeNum = LOCAL_NODE_NUM


class FakeIface:
    localNode = FakeLocalNode()


def make_transport() -> MeshtasticUsbTransport:
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    t = MeshtasticUsbTransport(emit, Settings(_env_file=None, transport="usb"))
    t._iface = FakeIface()
    return t


def routing_packet(from_num: int, error_reason: str = "NONE") -> dict:
    return {"from": from_num, "decoded": {"routing": {"errorReason": error_reason}}}


async def test_ack_from_remote_node_is_confirmed():
    t = make_transport()
    t._loop = asyncio.get_running_loop()

    def send(on_ack):
        on_ack(routing_packet(REMOTE_NODE_NUM))

    result = await t._ack_roundtrip(send, timeout=1)
    assert result == {"ack": True, "error_reason": "NONE"}


async def test_implicit_ack_from_local_node_is_not_confirmed():
    """El paquete de respuesta viene "from" el propio nodo local (radio local
    dándose por vencido tras agotar reintentos) — errorReason es "NONE" pero
    no hay confirmación real del destino; no debe marcarse como Confirmado."""
    t = make_transport()
    t._loop = asyncio.get_running_loop()

    def send(on_ack):
        on_ack(routing_packet(LOCAL_NODE_NUM))

    result = await t._ack_roundtrip(send, timeout=1)
    assert result == {"ack": False, "error_reason": "IMPLICIT_ACK_ONLY"}


async def test_explicit_nak_is_not_confirmed():
    t = make_transport()
    t._loop = asyncio.get_running_loop()

    def send(on_ack):
        on_ack(routing_packet(REMOTE_NODE_NUM, error_reason="MAX_RETRANSMIT"))

    result = await t._ack_roundtrip(send, timeout=1)
    assert result == {"ack": False, "error_reason": "MAX_RETRANSMIT"}
