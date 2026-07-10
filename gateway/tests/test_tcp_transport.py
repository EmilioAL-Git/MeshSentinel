"""Transporte TCP (ADR 0023): la única diferencia con USB es cómo se crea la
MeshInterface — estos tests fijan ese contrato: creación vía factory, host
obligatorio, construcción de TCPInterface con host/puerto, y que el
comportamiento compartido (enlace caído, ciclo del pump) es el heredado de
MeshtasticStreamTransport sin forks de lógica."""

import asyncio
import threading

import pytest

from gateway.config import Settings
from gateway.transports.factory import create_transport
from gateway.transports.meshtastic_stream import _FORCE_DISCONNECT
from gateway.transports.tcp import MeshtasticTcpTransport
from gateway.transports.usb import MeshtasticUsbTransport


async def _noop_emit(event_type, payload):  # noqa: ARG001
    pass


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, transport="tcp", tcp_host="192.168.1.50", **overrides)


def test_factory_creates_tcp_transport():
    t = create_transport(make_settings(), _noop_emit)
    assert isinstance(t, MeshtasticTcpTransport)
    assert t.name == "tcp"


def test_factory_still_creates_usb_transport():
    t = create_transport(Settings(_env_file=None, transport="usb"), _noop_emit)
    assert isinstance(t, MeshtasticUsbTransport)


def test_tcp_requires_host():
    with pytest.raises(ValueError, match="host"):
        create_transport(Settings(_env_file=None, transport="tcp"), _noop_emit)


def test_http_remains_unimplemented():
    with pytest.raises(NotImplementedError):
        create_transport(Settings(_env_file=None, transport="http", http_url="http://x"), _noop_emit)


def test_connect_blocking_builds_tcp_interface(monkeypatch):
    created: dict = {}

    class FakeTCPInterface:
        def __init__(self, hostname, portNumber):  # noqa: N803
            created["hostname"] = hostname
            created["portNumber"] = portNumber

    monkeypatch.setattr("meshtastic.tcp_interface.TCPInterface", FakeTCPInterface)
    t = MeshtasticTcpTransport(_noop_emit, make_settings(tcp_port=4404))
    iface = t._connect_blocking()
    assert isinstance(iface, FakeTCPInterface)
    assert created == {"hostname": "192.168.1.50", "portNumber": 4404}


def test_endpoint_description_is_host_port():
    t = MeshtasticTcpTransport(_noop_emit, make_settings())
    assert t._endpoint_description() == "192.168.1.50:4403"


# ── Comportamiento heredado: mismo pipeline que USB, sin reimplementar ───────


class FakeIface:
    def __init__(self, connected: bool = True) -> None:
        self.isConnected = threading.Event()
        if connected:
            self.isConnected.set()


async def test_execute_admin_rejects_when_link_down_like_usb():
    t = MeshtasticTcpTransport(_noop_emit, make_settings())
    t._loop = asyncio.get_running_loop()
    t._iface = FakeIface(connected=False)
    t.status = "connected"  # el pump aún no procesó la desconexión

    with pytest.raises(ConnectionError, match="not ready"):
        await t.execute_admin(
            {"operation_id": 1, "operation_type": "metadata.get", "params": {}, "target_node_id": "!a1b2c3d4"}
        )


async def test_pump_ignores_stale_disconnects_like_usb():
    t = MeshtasticTcpTransport(_noop_emit, make_settings())
    t._loop = asyncio.get_running_loop()
    current, previous = FakeIface(), FakeIface()
    t._iface = current
    t._queue.put_nowait(("disconnect", previous))
    t._queue.put_nowait(("disconnect", current))
    await asyncio.wait_for(t._pump_events(), timeout=2)
    assert t._counters["stale_disconnects"] == 1


async def test_force_disconnect_exits_pump():
    t = MeshtasticTcpTransport(_noop_emit, make_settings())
    t._loop = asyncio.get_running_loop()
    t._queue.put_nowait(_FORCE_DISCONNECT)
    await asyncio.wait_for(t._pump_events(), timeout=2)
