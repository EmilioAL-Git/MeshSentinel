"""Regresión: `_execute_ack_set` pasaba `node.nodeNum` directamente a
`iface._getOrCreateByNum`, pero `Node.nodeNum` puede ser `str` (p.ej.
"!e7ef4fb4") según cómo la librería haya cacheado ese `Node` — la propia
librería lo maneja con un `isinstance(self.nodeNum, int)` en `_sendAdmin`.
`_getOrCreateByNum` exige `int` (formatea con `:08x` internamente) y
revienta con `TypeError: Unknown format code 'x' for object of type 'str'`
si se le pasa una cadena. Bug detectado en producción al limpiar el passkey
PKC antes de cada intento (errata 5, ADR 0019)."""

import asyncio

from gateway.config import Settings
from gateway.transports.usb import MeshtasticUsbTransport

NODE_ID = "!e7ef4fb4"
NODE_NUM = 0xE7EF4FB4


class FakeLocalNode:
    nodeNum = 0xAAAAAAAA


class FakeNode:
    def __init__(self, node_num) -> None:
        self.nodeNum = node_num  # deliberadamente str, como en el bug real

    def ensureSessionKey(self) -> None:
        pass

    def _sendAdmin(self, msg, wantResponse=True, onResponse=None):  # noqa: ARG002
        onResponse({"from": 0x12345678, "decoded": {"routing": {"errorReason": "NONE"}}})


class FakeIface:
    localNode = FakeLocalNode()

    def __init__(self) -> None:
        self._node = FakeNode(NODE_ID)  # str, no int
        self.cache: dict[int, dict] = {}

    def getNode(self, node_id, requestChannels=False):  # noqa: ARG002
        return self._node

    def _getOrCreateByNum(self, node_num):
        # Réplica del comportamiento real: exige int, revienta con str.
        if not isinstance(node_num, int):
            raise TypeError(f"Unknown format code 'x' for object of type '{type(node_num).__name__}'")
        return self.cache.setdefault(node_num, {})


def make_transport() -> MeshtasticUsbTransport:
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    t = MeshtasticUsbTransport(emit, Settings(_env_file=None, transport="usb"))
    t._iface = FakeIface()
    return t


async def test_execute_ack_set_clears_passkey_by_numeric_node_id_not_node_nodenum():
    t = make_transport()
    t._loop = asyncio.get_running_loop()

    result = await t._execute_ack_set(
        NODE_ID, "ignored.set", {"subject_node_id": "!11112222"}, {"operation_id": 1, "timeout_seconds": 30}
    )

    assert result["ack"]["ack"] is True
    assert NODE_NUM in t._iface.cache  # se limpió la caché por el node_num correcto (int)
