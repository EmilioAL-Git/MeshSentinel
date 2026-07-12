"""Batch Engine (M2): preview, creación, control, finalización y progreso.

El motor coordina el pipeline existente: los tests reutilizan el
AdminOperationService real (con cola falsa) para verificar la integración.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from noc.adapters.persistence.admin_repositories import (
    SqlAdminBatchRepository,
    SqlAdminOperationRepository,
)
from noc.application.admin.batches import BatchScope, BatchService
from noc.application.admin.service import AdminOperationService
from noc.application.ingest import IngestService
from noc.application.node_filters import NodeFilters
from noc.config import Settings

NODES = [f"!0000000{i}" for i in range(1, 6)]  # 5 nodos


class FakeQueue:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        self.sent.append((gateway_id, envelope))


def make_settings(**overrides) -> Settings:
    overrides.setdefault("admin_rate_limit_per_minute", 1000)  # sin límite en tests
    return Settings(_env_file=None, **overrides)


def make_event(event_type: str, payload: dict, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


def result_event(op_id: int, state: str, result=None, error=None) -> dict:
    return make_event(
        "admin.operation", {"operation_id": op_id, "state": state, "result": result, "error": error}
    )


async def seed_nodes(session_factory) -> None:
    ingest = IngestService(session_factory)
    now = datetime.now(timezone.utc)
    for i, node_id in enumerate(NODES):
        ts = now - timedelta(hours=2) if i == 4 else now  # el último está offline
        await ingest.handle_event(
            make_event(
                "node.seen",
                {"node_id": node_id, "short_name": f"N{i}", "hw_model": "TBEAM"},
                ts,
            )
        )


def make_services(session_factory):
    settings = make_settings()
    queue = FakeQueue()
    admin = AdminOperationService(session_factory, queue, settings)
    batches = BatchService(session_factory, settings)
    admin.attach_batch_service(batches)
    return admin, batches, queue


PARAMS = {"section": "telemetry", "values": {"device_update_interval": 900}}


# ── Preview ──────────────────────────────────────────────────────────────────


async def test_preview_reports_offline_and_unknown(session_factory):
    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)

    preview = await batches.preview(
        "module_config.set",
        PARAMS,
        BatchScope(node_ids=[*NODES, "!ffffffff"]),
    )
    assert preview.total_selected == 6
    assert len(preview.eligible) == 5
    assert len(preview.excluded) == 1  # el desconocido
    assert preview.excluded[0].node_id == "!ffffffff"
    offline = next(p for p in preview.eligible if p.node_id == NODES[4])
    assert any("sin conexión" in w for w in offline.warnings)
    assert preview.requires_verification is True
    assert preview.estimated_seconds > 0


async def test_preview_with_filters_scope(session_factory):
    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)
    preview = await batches.preview(
        "metadata.get", {}, BatchScope(filters=NodeFilters(online=True))
    )
    # 4 online (el 5º lleva 2h callado)
    assert {p.node_id for p in preview.eligible} == set(NODES[:4])
    assert preview.requires_verification is False


async def test_preview_rejects_non_bulk_operation(session_factory):
    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)
    with pytest.raises(ValueError, match="bulk"):
        await batches.preview("owner.set", {"short_name": "X"}, BatchScope(node_ids=NODES[:2]))


# ── Creación e integración con el pipeline ───────────────────────────────────


async def test_create_batch_creates_operations(session_factory):
    await seed_nodes(session_factory)
    admin, batches, queue = make_services(session_factory)

    batch = await batches.create(
        "Cadencia telemetría", "module_config.set", PARAMS, NODES[:3], {"filters": {"tag": "x"}}
    )
    assert batch.status == "running"
    assert batch.node_ids == NODES[:3]

    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 100, batch_id=batch.id
        )
    assert len(ops) == 3
    assert all(o.batch_id == batch.id and o.status == "pending" for o in ops)
    assert all(o.params == PARAMS for o in ops)

    # El scheduler existente los despacha con normalidad (1 en vuelo por gw)
    await admin.tick()
    assert len(queue.sent) == 1


async def test_create_batch_with_forced_gateway_overrides_everything(session_factory):
    """Selección inteligente de gateway, Nivel 1: forzar en la creación del
    lote gana sobre cualquier preferencia y sobre el automático — cada
    operación del lote sale por la MISMA pasarela forzada."""
    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)

    batch = await batches.create(
        "Forzado a gw-manual", "module_config.set", PARAMS, NODES[:3], None,
        forced_gateway_id="gw-manual",
    )
    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 100, batch_id=batch.id
        )
    assert len(ops) == 3
    assert all(o.gateway_id == "gw-manual" for o in ops)
    assert all(o.gateway_note is None for o in ops)  # forzado: sin nota de fallback


async def test_batch_completion_and_progress(session_factory):
    await seed_nodes(session_factory)
    admin, batches, _ = make_services(session_factory)
    batch = await batches.create("B", "module_config.set", PARAMS, NODES[:3], None)

    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 100, batch_id=batch.id
        )
    ok = {"verify": "confirmed", "previous": {}, "requested": PARAMS, "verified": {}}

    await admin.handle_event(result_event(ops[0].id, "succeeded", result=ok))
    async with session_factory() as session:
        b = await SqlAdminBatchRepository(session).get(batch.id)
        progress = await batches.progress(session, b)
    assert b.status == "running"  # aún quedan 2
    assert progress["done"] == 1 and progress["total"] == 3
    assert progress["percent"] == pytest.approx(33.3, abs=0.1)

    await admin.handle_event(result_event(ops[1].id, "succeeded", result=ok))
    await admin.handle_event(result_event(ops[2].id, "succeeded", result=ok))

    async with session_factory() as session:
        b = await SqlAdminBatchRepository(session).get(batch.id)
        progress = await batches.progress(session, b)
    assert b.status == "completed"
    assert b.finished_at is not None
    assert progress["percent"] == 100.0
    assert progress["eta_seconds"] == 0


async def test_batch_completed_with_errors(session_factory):
    await seed_nodes(session_factory)
    admin, batches, _ = make_services(session_factory)
    batch = await batches.create("B", "metadata.get", {}, NODES[:2], None)
    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 100, batch_id=batch.id
        )
    # Agotar reintentos del primero
    for op in ops:
        async with session_factory() as session, session.begin():
            await SqlAdminOperationRepository(session).update_fields(op.id, {"attempts": 3})
    await admin.handle_event(result_event(ops[0].id, "timeout", error="no response"))
    await admin.handle_event(result_event(ops[1].id, "succeeded", result={"ok": True}))

    async with session_factory() as session:
        b = await SqlAdminBatchRepository(session).get(batch.id)
    assert b.status == "completed_with_errors"


# ── Control: pausa / reanudación / cancelación ───────────────────────────────


async def test_pause_blocks_dispatch_and_resume_releases(session_factory):
    await seed_nodes(session_factory)
    admin, batches, queue = make_services(session_factory)
    batch = await batches.create("B", "metadata.get", {}, NODES[:2], None)

    assert (await batches.pause(batch.id)).status == "paused"
    await admin.tick()
    assert queue.sent == []  # nada se despacha en pausa

    assert (await batches.resume(batch.id)).status == "running"
    await admin.tick()
    assert len(queue.sent) == 1


async def test_cancel_only_affects_not_started(session_factory):
    await seed_nodes(session_factory)
    admin, batches, queue = make_services(session_factory)
    batch = await batches.create("B", "metadata.get", {}, NODES[:3], None)

    await admin.tick()  # una pasa a queued (en vuelo)
    assert len(queue.sent) == 1
    in_flight_id = queue.sent[0][1]["payload"]["operation_id"]

    cancelled = await batches.cancel(batch.id)
    assert cancelled.status == "cancelled"

    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 100, batch_id=batch.id
        )
    by_id = {o.id: o for o in ops}
    # La que estaba en vuelo NO se toca; las pendientes sí
    assert by_id[in_flight_id].status == "queued"
    others = [o for o in ops if o.id != in_flight_id]
    assert all(o.status == "cancelled" for o in others)

    # El resultado tardío de la en-vuelo se procesa con normalidad y cierra el lote
    await admin.handle_event(result_event(in_flight_id, "succeeded", result={"ok": True}))
    async with session_factory() as session:
        b = await SqlAdminBatchRepository(session).get(batch.id)
    assert b.status == "cancelled"  # cancelado se mantiene (terminal)
    assert b.finished_at is not None
    assert by_id[in_flight_id]  # y la operación quedó auditada


async def test_cancel_terminal_batch_returns_none(session_factory):
    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)
    batch = await batches.create("B", "metadata.get", {}, NODES[:1], None)
    await batches.cancel(batch.id)
    assert await batches.cancel(batch.id) is None
    assert await batches.pause(batch.id) is None


# ── Historial ────────────────────────────────────────────────────────────────


async def test_history_filters(session_factory):
    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)
    b1 = await batches.create("Lote A", "metadata.get", {}, NODES[:2], None)
    await batches.create("Lote B", "module_config.set", PARAMS, NODES[2:4], None)
    await batches.cancel(b1.id)

    async with session_factory() as session:
        repo = SqlAdminBatchRepository(session)
        assert len(await repo.list_batches()) == 2
        assert [b.name for b in await repo.list_batches(status="cancelled")] == ["Lote A"]
        assert [b.name for b in await repo.list_batches(operation_type="module_config.set")] == ["Lote B"]
        assert [b.name for b in await repo.list_batches(node_id=NODES[3])] == ["Lote B"]
        assert await repo.list_batches(node_id="!ffffffff") == []


async def test_preview_endpoint_serializes_slots_dataclass(session_factory):
    """Regresión: NodePreview usa slots=True — el router debe usar asdict
    (mismo bug que capabilities en M1.1)."""
    from unittest.mock import Mock

    from noc.adapters.api.routers.admin_batches import PreviewIn, ScopeIn, preview_batch

    await seed_nodes(session_factory)
    _, batches, _ = make_services(session_factory)
    request = Mock()
    request.app.state.batches = batches

    out = await preview_batch(
        PreviewIn(
            operation_type="metadata.get",
            params={},
            scope=ScopeIn(node_ids=[*NODES[:2], "!ffffffff"]),
        ),
        request,
    )
    assert out.eligible_count == 2
    assert out.excluded_count == 1
    assert out.excluded[0].blockers


async def test_estimate_uses_rate_limit():
    service = BatchService(None, make_settings(admin_rate_limit_per_minute=6))  # type: ignore[arg-type]
    assert service.estimate_seconds(6) == 60
    assert service.estimate_seconds(60) == 600
    assert service.estimate_seconds(0) == 0
