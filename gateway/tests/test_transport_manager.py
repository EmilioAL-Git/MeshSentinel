"""Regresión de TransportManager (M5, ADR 0021): conexión dirigible en
caliente sin reiniciar el proceso, usando el transporte simulado (sin
hardware) para validar el ciclo test_connection -> connect -> disconnect y
la sincronización por generación (evita que una conexión vieja resuelva el
outcome de una nueva)."""

import asyncio

from gateway.config import Settings
from gateway.transport_manager import TransportManager


def make_manager() -> tuple[TransportManager, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []

    async def publish(event_type, payload):
        events.append((event_type, payload))

    settings = Settings(_env_file=None, transport="simulated", sim_node_count=2)
    return TransportManager(settings, publish), events


async def _test_connection_success() -> None:
    manager, events = make_manager()
    result = await manager.test_connection("simulated", {}, timeout=5.0)
    assert result["ok"] is True
    assert result["local_node_id"] is not None
    assert manager.transport is not None
    assert manager.transport.status == "connected"
    await manager.teardown()


def test_connection_success() -> None:
    asyncio.run(_test_connection_success())


async def _test_connect_then_disconnect_clears_transport() -> None:
    manager, events = make_manager()
    await manager.connect("simulated", {})
    await asyncio.sleep(0.05)
    assert manager.transport is not None

    await manager.disconnect()
    assert manager.transport is None
    last_status = [p for et, p in events if et == "gateway.status"][-1]
    assert last_status["status"] == "unassigned"


def test_connect_then_disconnect_clears_transport() -> None:
    asyncio.run(_test_connect_then_disconnect_clears_transport())


async def _test_reconnect_tears_down_previous_transport() -> None:
    manager, _events = make_manager()
    await manager.connect("simulated", {})
    await asyncio.sleep(0.05)
    first = manager.transport
    assert first is not None

    await manager.connect("simulated", {})
    await asyncio.sleep(0.05)
    second = manager.transport
    assert second is not None
    assert second is not first
    await manager.teardown()


def test_reconnect_tears_down_previous_transport() -> None:
    asyncio.run(_test_reconnect_tears_down_previous_transport())


async def _test_discover_returns_list() -> None:
    manager, _events = make_manager()
    result = await manager.discover()
    assert "request_id" in result
    assert isinstance(result["devices"], list)


def test_discover_returns_list() -> None:
    asyncio.run(_test_discover_returns_list())
