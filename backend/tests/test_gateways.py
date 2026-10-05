"""Gestión de gateways (M5, ADR 0021): CRUD, comandos correlacionados por
request_id, borrado real y reconciliación tras heartbeat."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from noc.adapters.gateways.launcher_client import LauncherContainerNotFound, LauncherError
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.nexus_repositories import SqlNexusOperationRepository
from noc.application.gateways.service import (
    GatewayAlreadyExistsError,
    GatewayHasActiveWorkError,
    GatewayService,
    GatewayStillConnectedError,
    LauncherUnavailableError,
)
from noc.application.ingest import IngestService
from noc.domain.admin.entities import AdminOperation
from noc.domain.nexus.entities import NexusOperation

GW = "gw-test"


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        self.sent.append((gateway_id, envelope))


def envelope(event_type: str, payload: dict, gateway_id: str = GW, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


async def seed_heartbeat(session_factory, status: str = "connected", ts: datetime | None = None) -> None:
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        envelope(
            "gateway.status", {"status": status, "transport": "usb", "local_node_id": "!aaaaaaaa"}, ts=ts
        )
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


async def test_configure_clears_stale_error_from_previous_device(session_factory):
    """Reconfigurar un gateway_id (borrado y vuelto a crear, o reasignado a
    otro dispositivo) no debe arrastrar el error/estado del anterior."""
    from noc.adapters.persistence.repositories import SqlGatewayRepository
    from noc.domain.nodes.entities import GatewayInfo

    async with session_factory() as session:
        repo = SqlGatewayRepository(session)
        await repo.configure(GW, "Casa", "tcp", {"host": "10.0.0.1"}, True, 0, "connected")
        await repo.upsert(
            GatewayInfo(
                gateway_id=GW,
                status="error",
                transport="tcp",
                detail="connect failed: Connection refused",
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    service = GatewayService(session_factory, FakeQueue())
    stale = await service.get(GW)
    assert stale is not None and stale.last_error is not None

    info = await service.configure(GW, "Casa", "tcp", {"host": "10.0.0.2"}, True, 0)
    assert info.last_error is None
    assert info.last_error_at is None
    assert info.last_connected_at is None
    assert info.status == "unassigned"


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


async def test_disconnect_sends_command_and_delete_removes_row(session_factory):
    """Borrado real (pedido explícito del usuario, ya no lógico): la fila
    desaparece del todo, incluso pidiendo include_deleted."""
    queue = FakeQueue()
    service = GatewayService(session_factory, queue)
    await service.configure(GW, "Casa", "usb", {})
    queue.sent.clear()

    info = await service.disconnect(GW)
    assert info is not None and info.desired_status == "disconnected"
    assert queue.sent[-1][1]["command_type"] == "command.gateway_disconnect"

    deleted = await service.delete(GW)
    assert deleted is True
    assert await service.list_all() == []
    assert await service.list_all(include_deleted=True) == []


async def test_delete_blocked_while_really_connected(session_factory):
    """Comprobación de vida pedida por el usuario, aparte del trabajo en
    vuelo: si el proceso reporta una conexión REAL activa (status
    "connected"), bloquea — hay que desconectarlo primero."""
    service = GatewayService(session_factory, FakeQueue())
    await service.configure(GW, "Casa", "usb", {})
    await seed_heartbeat(session_factory, status="connected")

    with pytest.raises(GatewayStillConnectedError):
        await service.delete(GW)
    assert (await service.get(GW)) is not None


async def test_delete_allowed_when_connected_status_is_stale(session_factory):
    """"connected" por sí solo no basta: un proceso muerto deja el último
    status congelado para siempre (nadie vuelve a heartbearlo) — sin la
    comprobación de frescura, una pasarela ya abandonada bloquearía su
    propio borrado para siempre."""
    service = GatewayService(session_factory, FakeQueue(), stale_after_seconds=90)
    await service.configure(GW, "Casa", "usb", {})
    old_ts = datetime.now(timezone.utc) - timedelta(seconds=200)
    await seed_heartbeat(session_factory, status="connected", ts=old_ts)

    assert await service.delete(GW) is True
    assert (await service.get(GW)) is None


async def test_delete_allowed_for_unassigned_gateway_even_if_its_process_keeps_heartbeating(session_factory):
    """Una pasarela que late pero nunca llega a "connected" de verdad (sin
    nodo local real) debe poder borrarse igual — vuelve limpia con el
    siguiente heartbeat si el proceso sigue vivo."""
    service = GatewayService(session_factory, FakeQueue())
    await service.configure(GW, "Casa", "usb", {})
    await seed_heartbeat(session_factory, status="unassigned")

    assert await service.delete(GW) is True
    assert (await service.get(GW)) is None


async def test_delete_unmanaged_returns_false(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    assert await service.delete(GW) is False


async def test_delete_blocked_by_active_admin_operation(session_factory):
    """Comprobación de seguridad pedida por el usuario: no borrar una
    pasarela con trabajo pendiente/en vuelo — la dejaría huérfana."""
    service = GatewayService(session_factory, FakeQueue())
    await service.configure(GW, "Casa", "usb", {})

    async with session_factory() as session, session.begin():
        await SqlAdminOperationRepository(session).create(
            AdminOperation(
                target_node_id="!00000001", gateway_id=GW,
                operation_type="metadata.get", params={}, status="queued",
            )
        )

    with pytest.raises(GatewayHasActiveWorkError):
        await service.delete(GW)
    # Sigue viva: el bloqueo no dejó la fila a medio borrar
    assert (await service.get(GW)) is not None


async def test_delete_blocked_by_active_nexus_operation(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    await service.configure(GW, "Casa", "usb", {})

    async with session_factory() as session, session.begin():
        await SqlNexusOperationRepository(session).create(
            NexusOperation(
                gateway_id=GW, target_kind="broadcast", target_value=None,
                command_name="INFO", args=[], text="/nexus INFO",
                destructive=False, requires_save=False, busy_seconds=0,
                status="sent",
            )
        )

    with pytest.raises(GatewayHasActiveWorkError):
        await service.delete(GW)


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


# ── Lanzador de contenedores (ADR 0028) ─────────────────────────────────────


class FakeLauncher:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, dict]] = []
        self.destroyed: list[str] = []
        self.fail_create = False
        self.fail_destroy = False
        self.not_found_on_destroy = False

    async def list_devices(self):
        return [{"port": "/dev/ttyACM0", "description": None, "vid": None, "pid": None, "serial_number": None}]

    async def create_container(self, gateway_id, transport_type, connection_params):
        if self.fail_create:
            raise LauncherError("docker rechazó la creación")
        self.created.append((gateway_id, transport_type, connection_params))
        return {"gateway_id": gateway_id, "container_id": "abc", "name": f"noc-gateway-{gateway_id}"}

    async def destroy_container(self, gateway_id):
        if self.not_found_on_destroy:
            raise LauncherContainerNotFound(gateway_id)
        if self.fail_destroy:
            raise LauncherError("docker rechazó el borrado")
        self.destroyed.append(gateway_id)


async def test_provision_creates_container_and_managed_row(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)

    info = await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})

    assert launcher.created == [(GW, "tcp", {"host": "10.0.0.5"})]
    assert info.managed is True
    assert info.container_managed is True
    assert info.transport_type == "tcp"


async def test_provision_rejects_existing_managed_gateway(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.configure(GW, "Casa", "usb", {})

    with pytest.raises(GatewayAlreadyExistsError):
        await service.provision(GW, "Otra", "tcp", {"host": "10.0.0.5"})
    assert launcher.created == []


async def test_provision_without_launcher_configured_raises(session_factory):
    service = GatewayService(session_factory, FakeQueue())
    with pytest.raises(LauncherUnavailableError):
        await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})


async def test_provision_leaves_no_row_when_launcher_fails(session_factory):
    launcher = FakeLauncher()
    launcher.fail_create = True
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)

    with pytest.raises(LauncherUnavailableError):
        await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})
    assert (await service.get(GW)) is None


async def test_delete_destroys_container_when_container_managed(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})

    assert await service.delete(GW) is True
    assert launcher.destroyed == [GW]
    assert (await service.get(GW)) is None


async def test_delete_treats_already_gone_container_as_success(session_factory):
    launcher = FakeLauncher()
    launcher.not_found_on_destroy = True
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})

    assert await service.delete(GW) is True
    assert (await service.get(GW)) is None


async def test_delete_aborts_row_when_launcher_destroy_fails(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})
    launcher.fail_destroy = True

    with pytest.raises(LauncherUnavailableError):
        await service.delete(GW)
    assert (await service.get(GW)) is not None


async def test_delete_does_not_call_launcher_for_external_gateway(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.configure(GW, "Casa", "usb", {})  # externo: container_managed=False

    assert await service.delete(GW) is True
    assert launcher.destroyed == []


async def test_list_launcher_devices_proxies_to_launcher(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    devices = await service.list_launcher_devices()
    assert devices[0]["port"] == "/dev/ttyACM0"


# ── Nodo virtual (ADR 0033) ──────────────────────────────────────────────────


async def test_virtual_node_port_must_be_valid_and_unique(session_factory):
    from noc.application.gateways.service import VirtualNodeConfigError

    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.provision("gw-a", "A", "tcp", {"host": "10.0.0.5", "vn_enabled": True, "vn_port": 4404})

    with pytest.raises(VirtualNodeConfigError, match="4404"):
        await service.provision("gw-b", "B", "tcp", {"host": "10.0.0.6", "vn_enabled": True, "vn_port": 4404})
    with pytest.raises(VirtualNodeConfigError):
        await service.provision("gw-b", "B", "tcp", {"host": "10.0.0.6", "vn_enabled": True, "vn_port": 80})
    # sin activar no se valida; con otro puerto, sí se permite
    await service.provision("gw-b", "B", "tcp", {"host": "10.0.0.6", "vn_port": 4404})
    await service.provision("gw-c", "C", "tcp", {"host": "10.0.0.7", "vn_enabled": True, "vn_port": 4405})
    # la propia pasarela puede conservar su puerto al editarse
    await service.update("gw-a", connection_params={"host": "10.0.0.5", "vn_enabled": True, "vn_port": 4404})


async def test_changing_virtual_node_publication_recreates_container_but_admin_flag_does_not(session_factory):
    launcher = FakeLauncher()
    service = GatewayService(session_factory, FakeQueue(), launcher=launcher)
    await service.provision(GW, "Oficina", "tcp", {"host": "10.0.0.5"})
    assert len(launcher.created) == 1

    # activar el nodo virtual cambia el puerto publicado: hay que recrear
    await service.update(GW, connection_params={"host": "10.0.0.5", "vn_enabled": True, "vn_port": 4404})
    assert len(launcher.created) == 2
    assert launcher.created[-1][2]["vn_enabled"] is True

    # cambiar solo la política de administración se aplica en caliente: sin recrear
    await service.update(
        GW, connection_params={"host": "10.0.0.5", "vn_enabled": True, "vn_port": 4404, "vn_allow_admin": True}
    )
    assert len(launcher.created) == 2

    # mover el puerto vuelve a recrear
    await service.update(GW, connection_params={"host": "10.0.0.5", "vn_enabled": True, "vn_port": 4410})
    assert len(launcher.created) == 3


async def test_virtual_node_runtime_status_is_persisted_from_heartbeat(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        envelope("gateway.status", {"status": "connected", "transport": "tcp",
                                    "virtual_node": {"port": 4404, "clients": 2, "allow_admin": False}})
    )
    service = GatewayService(session_factory, FakeQueue())
    info = await service.get(GW)
    assert info.virtual_node == {"port": 4404, "clients": 2, "allow_admin": False}
