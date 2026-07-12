"""Consola de actividad: eventos de ciclo de vida backend→UI.

El pipeline emite eventos `admin.operation` (dispatched/running/retry_scheduled/
finished) y `admin.batch` por el publicador compartido. Aquí se adjunta un
recorder al singleton (como hace main.py con el hub WS) y se verifica el
vocabulario, sin tocar Redis ni WebSockets.
"""

import uuid
from datetime import datetime, timezone

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.activity import activity
from noc.application.admin.batches import BatchService
from noc.application.admin.service import AdminOperationService
from noc.application.ingest import IngestService
from noc.config import Settings
from noc.domain.admin.entities import AdminOperation

NODE = "!00000001"


class FakeQueue:
    def __init__(self):
        self.sent = []

    async def enqueue(self, gateway_id, envelope):
        self.sent.append((gateway_id, envelope))


def make_event(event_type: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def seed_node(session_factory) -> None:
    await IngestService(session_factory).handle_event(
        make_event("node.seen", {"node_id": NODE, "short_name": "N1"})
    )


async def create_op(session_factory, **overrides) -> AdminOperation:
    async with session_factory() as session, session.begin():
        return await SqlAdminOperationRepository(session).create(
            AdminOperation(
                target_node_id=NODE,
                gateway_id="gw-test",
                operation_type=overrides.pop("operation_type", "metadata.get"),
                **overrides,
            )
        )


async def test_pipeline_emits_lifecycle_events(session_factory):
    await seed_node(session_factory)
    settings = Settings(_env_file=None, admin_rate_limit_per_minute=1000)
    service = AdminOperationService(session_factory, FakeQueue(), settings)
    service.attach_batch_service(BatchService(session_factory, settings))

    events: list[dict] = []

    async def recorder(event):
        events.append(event)

    activity.attach(recorder)
    try:
        op = await create_op(session_factory, max_attempts=2)
        await service.tick()  # despacho
        await service.handle_event(
            make_event("admin.operation", {"operation_id": op.id, "state": "running"})
        )
        # 1er fallo → reintento programado
        await service.handle_event(
            make_event("admin.operation", {"operation_id": op.id, "state": "failed", "error": "boom"})
        )
        await service.tick()  # redepacho... aún no (backoff), no debe romper
        # Forzamos el 2º intento agotando next_attempt_at
        async with session_factory() as session, session.begin():
            await SqlAdminOperationRepository(session).update_fields(
                op.id or 0, {"next_attempt_at": None}
            )
        await service.tick()
        # 2º fallo con max_attempts=2 → terminal
        await service.handle_event(
            make_event("admin.operation", {"operation_id": op.id, "state": "failed", "error": "boom"})
        )
    finally:
        activity.attach(None)

    states = [e["payload"]["state"] for e in events if e["event_type"] == "admin.operation"]
    assert states == ["dispatched", "running", "retry_scheduled", "dispatched", "finished"]
    # El último admin.operation (la narrativa activity.event del diario puede
    # llegar detrás, Actividad 2.0 Fase 1)
    finished = [e for e in events if e["event_type"] == "admin.operation"][-1]["payload"]
    assert finished["final_status"] == "failed"
    assert finished["node_id"] == NODE
    assert finished["operation_type"] == "metadata.get"
    # El envelope reutiliza el contrato v1
    assert events[0]["schema_version"] == 1
    assert events[0]["gateway_id"] == "gw-test"


async def test_verify_verdict_travels_in_finished_event(session_factory):
    await seed_node(session_factory)
    settings = Settings(_env_file=None, admin_rate_limit_per_minute=1000)
    service = AdminOperationService(session_factory, FakeQueue(), settings)

    events: list[dict] = []

    async def recorder(event):
        events.append(event)

    activity.attach(recorder)
    try:
        op = await create_op(
            session_factory, operation_type="owner.set", params={"short_name": "AB"}
        )
        await service.tick()
        await service.handle_event(
            make_event(
                "admin.operation",
                {"operation_id": op.id, "state": "succeeded", "result": {"verify": "confirmed"}},
            )
        )
    finally:
        activity.attach(None)

    finished = [e for e in events if e["payload"].get("state") == "finished"]
    assert len(finished) == 1
    assert finished[0]["payload"]["final_status"] == "succeeded"
    assert finished[0]["payload"]["verify"] == "confirmed"


async def test_batch_lifecycle_events(session_factory):
    await seed_node(session_factory)
    settings = Settings(_env_file=None, admin_rate_limit_per_minute=1000)
    batches = BatchService(session_factory, settings)
    service = AdminOperationService(session_factory, FakeQueue(), settings)
    service.attach_batch_service(batches)

    events: list[dict] = []

    async def recorder(event):
        events.append(event)

    activity.attach(recorder)
    try:
        batch = await batches.create("lote", "metadata.get", {}, [NODE], None)
        await batches.pause(batch.id or 0)
        await batches.resume(batch.id or 0)
        await service.tick()
        async with session_factory() as session, session.begin():
            repo = SqlAdminOperationRepository(session)
            ops = await repo.list_operations(None, None, 10, batch_id=batch.id)
        await service.handle_event(
            make_event("admin.operation", {"operation_id": ops[0].id, "state": "succeeded", "result": {}})
        )
    finally:
        activity.attach(None)

    batch_states = [e["payload"]["state"] for e in events if e["event_type"] == "admin.batch"]
    assert batch_states == ["created", "paused", "resumed", "completed"]
    completed = [e for e in events if e["payload"].get("state") == "completed"][0]
    assert completed["payload"]["counts"] == {"succeeded": 1}
