"""Regresión de `_ack_roundtrip` (ver ADR 0019, ambas erratas):

1. Un ACK implícito (`packet["from"]` == nodo local: el radio se rindió tras
   agotar reintentos y generó una respuesta sintética) NO es lo mismo que un
   ACK real del destino — pero comprobado en campo, tampoco implica fallo:
   con `wantResponse=True` ya corregido, un implícito se ha correspondido
   con una aplicación real en el dispositivo. Solo un NAK explícito
   (errorReason != "NONE") cuenta como fallo; el implícito se registra en
   `error_reason` para diagnóstico sin forzar reintento.
"""

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


async def test_implicit_ack_from_local_node_still_counts_as_confirmed():
    """No hay forma fiable de distinguir un implícito que sí se aplicó de uno
    que no (observado en campo en ambos sentidos) — se registra para
    diagnóstico pero no se fuerza reintento sobre una operación que, con
    wantResponse=True, probablemente sí se aplicó."""
    t = make_transport()
    t._loop = asyncio.get_running_loop()

    def send(on_ack):
        on_ack(routing_packet(LOCAL_NODE_NUM))

    result = await t._ack_roundtrip(send, timeout=1)
    assert result == {"ack": True, "error_reason": "IMPLICIT_ACK"}


async def test_explicit_nak_is_not_confirmed():
    t = make_transport()
    t._loop = asyncio.get_running_loop()

    def send(on_ack):
        on_ack(routing_packet(REMOTE_NODE_NUM, error_reason="MAX_RETRANSMIT"))

    result = await t._ack_roundtrip(send, timeout=1)
    assert result == {"ack": False, "error_reason": "MAX_RETRANSMIT"}
