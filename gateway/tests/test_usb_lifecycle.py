"""Regresión del ciclo de vida USB: iface.close() de la librería también publica
connection.lost, por lo que las desconexiones deben ir etiquetadas con su
interface y las de conexiones anteriores ignorarse — sin esto el transporte
entraba en un bucle perpetuo de reconexión y las operaciones admin fallaban
con 'Timed out waiting for connection completion'."""

import asyncio
import threading

import pytest

from gateway.config import Settings
from gateway.transports.usb import _FORCE_DISCONNECT, MeshtasticUsbTransport


class FakeIface:
    def __init__(self, connected: bool = True) -> None:
        self.isConnected = threading.Event()
        if connected:
            self.isConnected.set()
        self.devPath = "/dev/fake"


def make_transport() -> MeshtasticUsbTransport:
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    t = MeshtasticUsbTransport(emit, Settings(_env_file=None, transport="usb"))
    t._loop = asyncio.get_event_loop()
    return t


async def test_stale_disconnect_from_previous_iface_is_ignored():
    t = make_transport()
    t._loop = asyncio.get_running_loop()
    current, previous = FakeIface(), FakeIface()
    t._iface = current

    # Desconexión obsoleta (interface anterior) -> el pump NO debe salir
    t._queue.put_nowait(("disconnect", previous))
    # Desconexión real (interface actual) -> el pump SÍ debe salir
    t._queue.put_nowait(("disconnect", current))

    await asyncio.wait_for(t._pump_events(), timeout=2)
    assert t._counters["stale_disconnects"] == 1


async def test_force_disconnect_always_exits_pump():
    t = make_transport()
    t._loop = asyncio.get_running_loop()
    t._iface = FakeIface()
    t._queue.put_nowait(_FORCE_DISCONNECT)
    await asyncio.wait_for(t._pump_events(), timeout=2)


async def test_execute_admin_rejects_when_lib_link_down():
    """isConnected limpio en la librería -> error inmediato accionable, no 30 s."""
    t = make_transport()
    t._loop = asyncio.get_running_loop()
    t._iface = FakeIface(connected=False)
    t.status = "connected"  # el pump aún no procesó la desconexión

    with pytest.raises(ConnectionError, match="not ready"):
        await t.execute_admin(
            {"operation_id": 1, "operation_type": "metadata.get", "params": {}, "target_node_id": "!a1b2c3d4"}
        )


async def test_connection_loss_fails_pending_admin_waiters_immediately():
    t = make_transport()
    t._loop = asyncio.get_running_loop()
    future = t._loop.create_future()
    t._admin_waiters[("!a1b2c3d4", "getConfigResponse")] = future

    t._fail_pending_admin("connection lost during operation")

    with pytest.raises(ConnectionError, match="connection lost"):
        await future
    assert t._admin_waiters == {}


async def test_drain_queue_discards_stale_packets():
    t = make_transport()
    t._loop = asyncio.get_running_loop()
    t._queue.put_nowait(("packet", {"id": 1}))
    t._queue.put_nowait(("disconnect", FakeIface()))
    t._drain_queue()
    assert t._queue.empty()
