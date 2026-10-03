from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from noc.adapters.persistence.models import (
    AdminBatchModel,
    AdminOperationModel,
    AlertModel,
    AlertRuleModel,
    AuthLoginLogModel,
    ChatMessageModel,
    GatewayModel,
    NexusOperationModel,
    NexusOperationResponseModel,
    NodeModel,
    PositionModel,
    TelemetryModel,
)
from noc.adapters.persistence.retention import prune_all, storage_stats
from noc.application.retention import RetentionService
from noc.config import Settings

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=400)
RECENT = NOW - timedelta(days=1)


def _settings(**over) -> Settings:
    base = {f: 0 for f in Settings.model_fields if f.startswith("retention_") and f.endswith("_days")}
    base.update(over)
    return Settings(**base)


async def _count(session_factory, model) -> int:
    async with session_factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def _seed_node(session_factory, node_id: str, last_seen: datetime) -> None:
    async with session_factory() as s:
        s.add(NodeModel(id=node_id, first_seen_at=last_seen, last_seen_at=last_seen))
        await s.commit()


async def test_zero_days_keeps_everything(session_factory):
    await _seed_node(session_factory, "!00000001", OLD)
    async with session_factory() as s:
        s.add(TelemetryModel(node_id="!00000001", kind="device", received_at=OLD))
        await s.commit()
    assert await prune_all(session_factory, _settings(), NOW) == {}
    assert await _count(session_factory, TelemetryModel) == 1


async def test_timeseries_pruned_by_own_window(session_factory):
    await _seed_node(session_factory, "!00000001", RECENT)
    async with session_factory() as s:
        s.add_all(
            [
                TelemetryModel(node_id="!00000001", kind="device", received_at=OLD),
                TelemetryModel(node_id="!00000001", kind="device", received_at=RECENT),
                PositionModel(node_id="!00000001", latitude=1, longitude=1, received_at=OLD),
                ChatMessageModel(from_node_id="!00000001", text="x", received_at=OLD),
                AuthLoginLogModel(username="a", event="login", created_at=OLD),
            ]
        )
        await s.commit()
    # Solo telemetría tiene plazo: posiciones/chat/login quedan intactos
    res = await prune_all(session_factory, _settings(retention_telemetry_days=30), NOW)
    assert res == {"telemetry": 1}
    assert await _count(session_factory, TelemetryModel) == 1
    assert await _count(session_factory, PositionModel) == 1
    assert await _count(session_factory, ChatMessageModel) == 1
    assert await _count(session_factory, AuthLoginLogModel) == 1


async def test_only_resolved_alerts_are_pruned(session_factory):
    async with session_factory() as s:
        rule = AlertRuleModel(
            name="r", rule_type="low_battery", enabled=True, severity="warning",
            threshold=20, duration_seconds=0, cooldown_seconds=0, params={},
            created_at=OLD, updated_at=OLD,
        )
        s.add(rule)
        await s.flush()

        def alert(status, resolved):
            return AlertModel(
                rule_id=rule.id, rule_name="r", subject_type="node", subject_id="!1",
                severity="warning", status=status, message="m", fired_at=OLD, resolved_at=resolved,
            )

        s.add_all([alert("resolved", OLD), alert("firing", None), alert("acknowledged", None)])
        await s.commit()
    res = await prune_all(session_factory, _settings(retention_alerts_days=30), NOW)
    assert res == {"alerts": 1}
    assert await _count(session_factory, AlertModel) == 2


async def test_admin_prunes_terminal_ops_then_empty_batches(session_factory):
    await _seed_node(session_factory, "!00000001", RECENT)
    async with session_factory() as s:
        done = AdminBatchModel(
            status="completed", operation_type="x", created_at=OLD, finished_at=OLD,
            node_ids=[], name="done", params={},
        )
        live = AdminBatchModel(
            status="running", operation_type="x", created_at=OLD,
            node_ids=[], name="live", params={},
        )
        s.add_all([done, live])
        await s.flush()
        for status, batch in (("succeeded", done), ("queued", live)):
            s.add(
                AdminOperationModel(
                    batch_id=batch.id, gateway_id="gw", target_node_id="!00000001",
                    operation_type="metadata.get", status=status, params={},
                    attempts=0, max_attempts=3, created_at=OLD,
                    finished_at=OLD if status == "succeeded" else None,
                )
            )
        await s.commit()
    res = await prune_all(session_factory, _settings(retention_admin_days=30), NOW)
    assert res == {"admin": 2}  # 1 operación terminal + 1 lote terminado
    assert await _count(session_factory, AdminOperationModel) == 1  # la "queued" sobrevive
    assert await _count(session_factory, AdminBatchModel) == 1  # el lote vivo sobrevive


async def test_nexus_prunes_terminal_with_responses(session_factory):
    async with session_factory() as s:
        ops = []
        for status in ("confirmed", "pending"):
            op = NexusOperationModel(
                gateway_id="gw", target_kind="broadcast", target_value="", command_name="INFO",
                args=[], text="/nexus INFO", status=status, created_at=OLD,
                response_at=OLD if status == "confirmed" else None,
            )
            s.add(op)
            ops.append(op)
        await s.flush()
        s.add(NexusOperationResponseModel(
            operation_id=ops[0].id, from_node_id="!1", response_text="r", response_kind="raw", received_at=OLD))
        await s.commit()
    res = await prune_all(session_factory, _settings(retention_nexus_days=30), NOW)
    assert res == {"nexus": 1}
    assert await _count(session_factory, NexusOperationModel) == 1
    assert await _count(session_factory, NexusOperationResponseModel) == 0


async def test_node_pruning_protects_local_gateway_nodes_and_cascades(session_factory):
    await _seed_node(session_factory, "!0000000a", OLD)  # inactivo → se borra
    await _seed_node(session_factory, "!0000000b", OLD)  # nodo local de pasarela → se queda
    await _seed_node(session_factory, "!0000000c", RECENT)  # activo → se queda
    async with session_factory() as s:
        s.add(GatewayModel(id="gw-x", transport="simulated", status="connected",
                           local_node_id="!0000000b", updated_at=RECENT))
        s.add(TelemetryModel(node_id="!0000000a", kind="device", received_at=RECENT))
        await s.commit()
    res = await prune_all(session_factory, _settings(retention_nodes_days=30), NOW)
    assert res == {"nodes": 1}
    async with session_factory() as s:
        ids = set((await s.scalars(select(NodeModel.id))).all())
    assert ids == {"!0000000b", "!0000000c"}
    assert await _count(session_factory, TelemetryModel) == 0  # historia propia arrastrada


async def test_service_records_last_run_and_survives_errors(session_factory):
    service = RetentionService(session_factory, _settings(retention_telemetry_days=30))
    run = await service.run_once("manual")
    assert run.error is None and service.last_run is run and not service.running

    async def boom(*a, **k):
        raise RuntimeError("db down")

    import noc.application.retention as mod

    original = mod.prune_all
    mod.prune_all = boom
    try:
        failed = await service.run_once("scheduled")
    finally:
        mod.prune_all = original
    assert failed.error == "db down"


async def test_storage_stats_lists_tables_with_rows(session_factory):
    await _seed_node(session_factory, "!00000001", RECENT)
    async with session_factory() as s:
        stats = await storage_stats(s)
    by = {t.table: t for t in stats.tables}
    assert by["nodes"].rows == 1 and by["nodes"].oldest is not None
    assert by["node_telemetry"].rows == 0 and by["node_telemetry"].oldest is None
    assert stats.engine in ("sqlite", "postgresql")
