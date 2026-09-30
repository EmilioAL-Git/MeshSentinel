"""Transporte "idle" (piscina de repuestos M6.3): no conecta a nada, solo
late como "unassigned" hasta que TransportManager lo sustituye vía
connect()/test_connection() — mismo mecanismo de M5, sin tocarlo."""

import asyncio

from gateway.config import Settings
from gateway.transport_manager import TransportManager
from gateway.transports.factory import create_transport
from gateway.transports.idle import IdleTransport


async def _noop_emit(event_type, payload):  # noqa: ARG001
    pass


def test_factory_returns_idle_transport() -> None:
    settings = Settings(_env_file=None, transport="idle")
    transport = create_transport(settings, _noop_emit)
    assert isinstance(transport, IdleTransport)
    assert transport.name == "idle"


async def _run_emits_unassigned_then_blocks_until_close() -> None:
    events: list[tuple[str, dict]] = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    transport = IdleTransport(emit)
    task = asyncio.create_task(transport.run())
    await asyncio.sleep(0.05)

    assert not task.done()
    assert [p for _, p in events][-1]["status"] == "unassigned"

    await transport.close()
    await asyncio.wait_for(task, timeout=1.0)


def test_run_emits_unassigned_then_blocks_until_close() -> None:
    asyncio.run(_run_emits_unassigned_then_blocks_until_close())


async def _manager_reclaims_idle_spare_via_connect() -> None:
    events: list[tuple[str, dict]] = []

    async def publish(event_type, payload):
        events.append((event_type, payload))

    settings = Settings(_env_file=None, transport="idle")
    manager = TransportManager(settings, publish)
    await manager.start_from_env()
    await asyncio.sleep(0.05)
    assert manager.transport is not None
    assert manager.transport.status == "unassigned"

    # Reclamado real: la UI manda command.gateway_connect con el transporte
    # de verdad, TransportManager sustituye el idle sin código nuevo.
    await manager.connect("simulated", {})
    await asyncio.sleep(0.05)
    assert manager.transport is not None
    assert manager.transport.name == "simulated"
    await manager.teardown()


def test_manager_reclaims_idle_spare_via_connect() -> None:
    asyncio.run(_manager_reclaims_idle_spare_via_connect())
