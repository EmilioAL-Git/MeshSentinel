import uuid
from datetime import datetime, timedelta, timezone

import pytest

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.admin.registry import validate_operation
from noc.application.admin.service import AdminOperationService, retry_delay_seconds
from noc.application.ingest import IngestService
from noc.config import Settings
from noc.domain.admin.entities import AdminOperation

NODE = "!a1b2c3d4"


# ── Registro de capacidades ──────────────────────────────────────────────────


def test_registry_validates_sections():
    assert validate_operation("config.get", {"section": "lora"}) == {"section": "lora"}
    assert validate_operation("metadata.get", {}) == {}
    with pytest.raises(ValueError):
        validate_operation("config.get", {"section": "nope"})
    with pytest.raises(ValueError):
        validate_operation("metadata.get", {"unexpected": 1})
    with pytest.raises(ValueError):
        validate_operation("config.set", {})  # SET no existe en M1.1


def test_retry_backoff_is_exponential_and_capped():
    assert retry_delay_seconds(1) == 10
    assert retry_delay_seconds(2) == 20
    assert retry_delay_seconds(3) == 40
    assert retry_delay_seconds(10) == 300


# ── Pipeline completo con cola falsa ─────────────────────────────────────────


class FakeQueue:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        self.sent.append((gateway_id, envelope))


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def result_event(op_id: int, state: str, result=None, error=None) -> dict:
    return {
        "schema_version": 1,
        "event_type": "admin.operation",
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"operation_id": op_id, "state": state, "result": result, "error": error},
    }


async def create_op(session_factory, **overrides) -> AdminOperation:
    defaults = dict(
        target_node_id=NODE,
        gateway_id="gw-test",
        operation_type="metadata.get",
        timeout_seconds=120,
        max_attempts=3,
    )
    defaults.update(overrides)
    async with session_factory() as session, session.begin():
        return await SqlAdminOperationRepository(session).create(AdminOperation(**defaults))


async def get_op(session_factory, op_id: int) -> AdminOperation:
    async with session_factory() as session:
        op = await SqlAdminOperationRepository(session).get(op_id)
    assert op is not None
    return op


async def test_dispatch_and_success_flow(session_factory):
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op = await create_op(session_factory)

    await service.tick()
    assert len(queue.sent) == 1
    gateway_id, envelope = queue.sent[0]
    assert gateway_id == "gw-test"
    assert envelope["command_type"] == "command.send_admin"
    assert envelope["payload"]["operation_id"] == op.id
    assert (await get_op(session_factory, op.id)).status == "queued"

    await service.handle_event(result_event(op.id, "running"))
    assert (await get_op(session_factory, op.id)).status == "running"

    await service.handle_event(result_event(op.id, "succeeded", result={"firmwareVersion": "2.7.0"}))
    final = await get_op(session_factory, op.id)
    assert final.status == "succeeded"
    assert final.result == {"firmwareVersion": "2.7.0"}
    assert final.duration_ms is not None
    assert final.finished_at is not None


async def test_one_in_flight_per_gateway(session_factory):
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op1 = await create_op(session_factory)
    op2 = await create_op(session_factory)

    await service.tick()
    await service.tick()
    assert len(queue.sent) == 1  # la segunda espera a que la primera termine

    await service.handle_event(result_event(op1.id, "succeeded", result={}))
    await service.tick()
    assert len(queue.sent) == 2
    assert queue.sent[1][1]["payload"]["operation_id"] == op2.id


async def test_failure_retries_then_final(session_factory):
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op = await create_op(session_factory, max_attempts=2)

    await service.tick()  # attempt 1
    await service.handle_event(result_event(op.id, "timeout", error="no response"))
    retried = await get_op(session_factory, op.id)
    assert retried.status == "pending"  # reintento programado
    assert retried.attempts == 1
    assert retried.next_attempt_at is not None

    # Forzar que el reintento esté listo ya
    async with session_factory() as session, session.begin():
        await SqlAdminOperationRepository(session).update_fields(
            op.id, {"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
    await service.tick()  # attempt 2
    assert len(queue.sent) == 2

    await service.handle_event(result_event(op.id, "timeout", error="still nothing"))
    final = await get_op(session_factory, op.id)
    assert final.status == "timeout"  # max_attempts agotados
    assert final.error == "still nothing"


async def test_ack_only_favorite_ignored_resend_redundantly_until_max_attempts(session_factory):
    """ADR 0019 errata 4: sin GET posible, un ACK aislado no garantiza que se
    aplicó de verdad (visto en producción en ambos sentidos) — favorito/
    ignorado remotos reenvían hasta max_attempts aunque ya haya un ACK."""
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op = await create_op(session_factory, operation_type="favorite.set", max_attempts=3)
    unavailable = {"ack": {"ack": True, "error_reason": "NONE"}, "verify": "unavailable"}

    await service.tick()  # intento 1
    await service.handle_event(result_event(op.id, "succeeded", result=unavailable))
    after1 = await get_op(session_factory, op.id)
    assert after1.status == "pending"  # reenvío redundante, NO terminal todavía
    assert after1.attempts == 1
    assert after1.next_attempt_at is not None

    async with session_factory() as session, session.begin():
        await SqlAdminOperationRepository(session).update_fields(
            op.id, {"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
    await service.tick()  # intento 2
    await service.handle_event(result_event(op.id, "succeeded", result=unavailable))
    after2 = await get_op(session_factory, op.id)
    assert after2.status == "pending"
    assert after2.attempts == 2

    async with session_factory() as session, session.begin():
        await SqlAdminOperationRepository(session).update_fields(
            op.id, {"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
    await service.tick()  # intento 3 (último)
    await service.handle_event(result_event(op.id, "succeeded", result=unavailable))
    final = await get_op(session_factory, op.id)
    assert final.status == "succeeded_unconfirmed"  # ahora sí terminal
    assert final.attempts == 3
    assert final.finished_at is not None
    assert len(queue.sent) == 3


async def test_ack_only_op_without_verify_unavailable_does_not_resend(session_factory):
    """Solo se reenvía redundantemente cuando el resultado es
    succeeded_unconfirmed; un ACK ya "succeeded" de verdad no necesita
    reenvíos (y metadata.get, sin always_resend, tampoco)."""
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op = await create_op(session_factory, operation_type="favorite.set", max_attempts=3)

    await service.tick()
    await service.handle_event(result_event(op.id, "succeeded", result={"ack": {"ack": True}}))
    final = await get_op(session_factory, op.id)
    assert final.status == "succeeded"  # sin "verify" en el resultado -> no unconfirmed
    assert final.finished_at is not None
    assert len(queue.sent) == 1


async def test_watchdog_expires_stuck_operations(session_factory):
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op = await create_op(session_factory, max_attempts=1)
    await service.tick()

    # Simular gateway muerto: la operación quedó en queued hace mucho
    stale = datetime.now(timezone.utc) - timedelta(seconds=op.timeout_seconds + 120)
    async with session_factory() as session, session.begin():
        await SqlAdminOperationRepository(session).update_fields(op.id, {"queued_at": stale})

    await service.tick()
    final = await get_op(session_factory, op.id)
    assert final.status == "timeout"
    assert "watchdog" in (final.error or "")


async def test_late_result_for_cancelled_operation_is_ignored(session_factory):
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings())
    op = await create_op(session_factory)
    async with session_factory() as session, session.begin():
        await SqlAdminOperationRepository(session).update_fields(op.id, {"status": "cancelled"})

    await service.handle_event(result_event(op.id, "succeeded", result={}))
    assert (await get_op(session_factory, op.id)).status == "cancelled"


async def test_rate_limit_budget(session_factory):
    queue = FakeQueue()
    service = AdminOperationService(session_factory, queue, make_settings(admin_rate_limit_per_minute=1))
    await create_op(session_factory, gateway_id="gw-a")
    await create_op(session_factory, gateway_id="gw-b")

    await service.tick()
    await service.tick()
    # Dos gateways libres, pero el presupuesto global es 1/min
    assert len(queue.sent) == 1


# ── Regresiones de la API (bugs encontrados en validación M1.1) ──────────────


async def test_capabilities_endpoint_serializes_slots_dataclass():
    """Regresión: OperationSpec usa slots=True (sin __dict__) — debe usarse asdict."""
    from noc.adapters.api.routers.admin_operations import capabilities

    caps = await capabilities()
    types = {c.operation_type for c in caps}
    assert {"metadata.get", "nodeinfo.get", "config.get", "module_config.get"} <= types
    assert {"owner.set", "position.set_fixed"} <= types  # M1.3
    assert "section" in next(c for c in caps if c.operation_type == "config.get").param_choices


async def test_create_operation_endpoint_after_implicit_transaction(session_factory):
    """Regresión: el SELECT del nodo abre transacción implícita; el
    session.begin() posterior rompía con 'transaction already begun' (500)."""
    from noc.adapters.api.routers.admin_operations import OperationIn, create_operation

    ingest = IngestService(session_factory)
    await ingest.handle_event(
        {
            "schema_version": 1,
            "event_type": "node.seen",
            "event_id": str(uuid.uuid4()),
            "gateway_id": "gw-test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"node_id": NODE},
        }
    )
    async with session_factory() as session:
        out = await create_operation(
            OperationIn(node_id=NODE, operation_type="nodeinfo.get"), session, None
        )
    assert out.status == "pending"
    assert out.gateway_id == "gw-test"
    # Persistida de verdad (commit efectivo)
    assert (await get_op(session_factory, out.id)).operation_type == "nodeinfo.get"


async def test_node_ingest_supports_pipeline(session_factory):
    """El registry conoce el gateway del nodo: base para enrutar operaciones."""
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        {
            "schema_version": 1,
            "event_type": "node.seen",
            "event_id": str(uuid.uuid4()),
            "gateway_id": "gw-test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"node_id": NODE},
        }
    )
    from noc.adapters.persistence.repositories import SqlNodeRepository

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE)
    assert node is not None and node.gateway_id == "gw-test"
