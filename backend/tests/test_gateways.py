"""Gestión de gateways (M5, ADR 0021): CRUD, comandos correlacionados por
request_id, borrado lógico y reconciliación tras heartbeat."""

import uuid
from datetime import datetime, timedelta, timezone

from noc.application.gateways.service import GatewayService
from noc.application.ingest import IngestService

GW = "gw-test"


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        self.sent.append((gateway_id, envelope))


def envelope(event_type: str, payload: dict, gateway_id: str = GW) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def seed_heartbeat(session_factory, status: str = "connected", ts: datetime | None = None) -> None:
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        envelope("gateway.status", {"status": status, "transport": "usb", "local_node_id": "!aaaaaaaa"})
    )


# ── Configuración ────────────────────────────────────────────────────────────


async def test_configure_creates_row_and_sends_connect(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    info = await service.configure(GW, "Casa", "usb", {"device": "/dev/cu.usbmodem1"})

    assert info.name == "Casa"
    assert info.managed is True
    assert info.desired_status == "connected"
    assert [c for _, c in queue.sent][-1]["command_type"] == "command.gateway_connect"

    listed = await service.list_all()
    assert listed[0].name == "Casa"


async def test_configure_disabled_does_not_send_connect(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {}, enabled=False)
    assert queue.sent == []


async def test_import_legacy_claims_existing_heartbeat_row(session_factory):
    await seed_heartbeat(session_factory)
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)

    info = await service.import_legacy(GW)
    assert info is not None
    assert info.managed is True
    assert info.name == GW
    assert info.transport_type == "usb"
    # Ya conectado por el heartbeat: no hace falta reenviar un connect
    assert queue.sent == []


async def test_import_legacy_unknown_gateway_returns_none(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    assert await service.import_legacy("gw-unknown") is None


async def test_update_partial_edit_reconnects_with_new_params(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {"device": "/dev/cu.a"})
    queue.sent.clear()

    info = await service.update(GW, connection_params={"device": "/dev/cu.b"})
    assert info is not None
    assert info.connection_params == {"device": "/dev/cu.b"}
    last = queue.sent[-1][1]
    assert last["command_type"] == "command.gateway_connect"
    assert last["payload"]["connection_params"] == {"device": "/dev/cu.b"}


async def test_update_unmanaged_gateway_returns_none(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    assert await service.update(GW, name="X") is None


async def test_update_disable_sends_disconnect(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {})
    queue.sent.clear()

    info = await service.update(GW, enabled=False)
    assert info is not None
    assert info.enabled is False
    assert info.desired_status == "disconnected"
    assert queue.sent[-1][1]["command_type"] == "command.gateway_disconnect"


# ── Conectar / desconectar / eliminar ────────────────────────────────────────


async def test_connect_and_disconnect_require_managed_gateway(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    assert await service.connect(GW) is None
    assert await service.disconnect(GW) is None


async def test_disconnect_sends_command_and_soft_delete_disconnects(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {})
    queue.sent.clear()

    info = await service.disconnect(GW)
    assert info is not None and info.desired_status == "disconnected"
    assert queue.sent[-1][1]["command_type"] == "command.gateway_disconnect"

    deleted = await service.delete(GW)
    assert deleted is True
    remaining = await service.list_all()
    assert remaining == []  # excluido por defecto (borrado lógico, no físico)
    all_rows = await service.list_all(include_deleted=True)
    assert all_rows[0].enabled is False and all_rows[0].deleted_at is not None


async def test_delete_unmanaged_returns_false(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    assert await service.delete(GW) is False


# ── Descubrimiento / prueba de conexión: correlación por request_id ─────────


async def test_discover_resolves_from_matching_event(session_factory):
    service = GatewayService(session_factory, FakeQueue())

    import asyncio

    async def responder():
        # Espera a que se registre el waiter y responde con el request_id real
        while not service._waiters:
            await asyncio.sleep(0)
        request_id = next(iter(service._waiters))
        await service.handle_event(
            envelope("gateway.devices_found", {"request_id": request_id, "devices": [{"port": "/dev/cu.x"}]})
        )

    devices, _ = await asyncio.gather(service.discover(GW), responder())
    assert devices == [{"port": "/dev/cu.x"}]


async def test_discover_times_out_without_response(session_factory, monkeypatch):
    import noc.application.gateways.service as service_mod

    monkeypatch.setattr(service_mod, "DISCOVER_TIMEOUT_SECONDS", 0.05)
    service = GatewayService(session_factory, FakeQueue())
    devices = await service.discover(GW)
    assert devices == []


async def test_handle_event_ignores_unrelated_event_types(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    await service.handle_event(envelope("node.seen", {"node_id": "!aaaaaaaa"}))  # no debe fallar


# ── Reconciliación tras heartbeat (ADR 0021 §5) ──────────────────────────────


async def test_reconciliation_resends_connect_when_gateway_reappears_stale(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {"device": "/dev/cu.a"})
    queue.sent.clear()

    # gateway_stale_after_seconds muy bajo: cualquier hueco cuenta como "stale"
    ingest = IngestService(session_factory, service, gateway_stale_after_seconds=0)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    await ingest.handle_event(
        {
            "schema_version": 1,
            "event_type": "gateway.status",
            "event_id": str(uuid.uuid4()),
            "gateway_id": GW,
            "timestamp": later.isoformat(),
            "payload": {"status": "connecting", "transport": "usb"},
        }
    )

    reconnects = [c for _, c in queue.sent if c["command_type"] == "command.gateway_connect"]
    assert len(reconnects) == 1
    assert reconnects[0]["payload"]["connection_params"] == {"device": "/dev/cu.a"}


async def test_reconciliation_skips_when_not_stale(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {"device": "/dev/cu.a"})
    queue.sent.clear()

    ingest = IngestService(session_factory, service, gateway_stale_after_seconds=90)
    soon = datetime.now(timezone.utc) + timedelta(seconds=1)
    await ingest.handle_event(
        {
            "schema_version": 1,
            "event_type": "gateway.status",
            "event_id": str(uuid.uuid4()),
            "gateway_id": GW,
            "timestamp": soon.isoformat(),
            "payload": {"status": "connected", "transport": "usb"},
        }
    )
    assert queue.sent == []


async def test_heartbeat_upsert_never_touches_config_fields(session_factory):
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {"device": "/dev/cu.a"}, priority=7)

    await seed_heartbeat(session_factory, status="connected")

    info = await service.get(GW)
    assert info is not None
    assert info.name == "Casa"
    assert info.priority == 7
    assert info.connection_params == {"device": "/dev/cu.a"}
