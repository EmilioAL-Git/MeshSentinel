"""Fase de hardening: Registro persistente, agregados reales y coherencia
preview/create de lotes.

- activity_log: el MISMO envelope del WS se persiste (writer en background,
  cola acotada, poda por tamaño) y se recupera más reciente primero.
- counts: los contadores del HUD/StatusBar/insignias salen de agregados SQL,
  con la misma semántica de grupo que la UI (no-nodo siempre dentro,
  CRITICAL fuera del grupo también cuenta).
- preview de lotes: misma resolución de gateways que la ejecución — un nodo
  cuya única pasarela está eliminada se bloquea YA en la simulación.
"""

from datetime import datetime, timezone

from noc.adapters.persistence.activity_repositories import SqlActivityLogRepository
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from noc.adapters.persistence.organization_repositories import SqlGroupRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.application.activity import ActivityPublisher
from noc.application.activity_events import ActivityEvent
from noc.application.activity_log import ActivityLogWriter
from noc.application.admin.batches import BatchScope, BatchService
from noc.application.ingest import IngestService
from noc.config import Settings
from noc.domain.admin.entities import AdminOperation
from noc.domain.alerts.entities import Alert, AlertRule
from noc.domain.nodes.entities import Group

from test_batches import make_event  # envelope de test compartido


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def make_envelope(i: int, node_id: str | None = "!00000001") -> dict:
    return {
        "schema_version": 1,
        "event_type": "activity.event",
        "event_id": f"evt-{i:04d}",
        "gateway_id": "gw-01",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "source": "mesh",
            "severity": "info",
            "icon": "📊",
            "title": f"Evento {i}",
            "node_id": node_id,
        },
    }


# ── Registro persistente ─────────────────────────────────────────────────────


async def test_activity_log_roundtrip_and_pagination(session_factory):
    async with session_factory() as session, session.begin():
        repo = SqlActivityLogRepository(session)
        await repo.add_many([make_envelope(i) for i in range(1, 6)])

    async with session_factory() as session:
        repo = SqlActivityLogRepository(session)
        items = await repo.list_recent(limit=3)
        # Más recientes primero (mismo orden que el feed en vivo)
        assert [it["event_id"] for it in items] == ["evt-0005", "evt-0004", "evt-0003"]
        # El envelope recuperado es indistinguible del que viajó por el WS
        assert items[0]["event_type"] == "activity.event"
        assert items[0]["payload"]["title"] == "Evento 5"
        assert items[0]["gateway_id"] == "gw-01"
        # Paginación hacia atrás por log_id
        older = await repo.list_recent(limit=10, before_id=items[-1]["log_id"])
        assert [it["event_id"] for it in older] == ["evt-0002", "evt-0001"]
        # Filtro por nodo
        assert await repo.list_recent(limit=10, node_id="!deadbeef") == []


async def test_activity_log_server_filters(session_factory):
    """Consola profesional del Registro: filtros de servidor por pasarela,
    grupo (eventos sin nodo siempre visibles) y búsqueda de texto libre."""
    async with session_factory() as session, session.begin():
        repo = SqlActivityLogRepository(session)
        e1 = make_envelope(1, node_id="!00000001")
        e2 = make_envelope(2, node_id="!00000002")
        e2["gateway_id"] = "gw-02"
        e2["payload"]["title"] = "Posición actualizada"
        e3 = make_envelope(3, node_id=None)  # evento de sistema/pasarela
        e3["payload"]["source"] = "gateway"
        await repo.add_many([e1, e2, e3])

        ingest = IngestService(session_factory)
    # nodos + grupo con SOLO !00000001
    ingest = IngestService(session_factory)
    for nid in ("!00000001", "!00000002"):
        await ingest.handle_event(make_event("node.seen", {"node_id": nid}))
    async with session_factory() as session, session.begin():
        group = await SqlGroupRepository(session).create(Group(name="g-log"))
        await SqlGroupRepository(session).add_member(group.id or 0, "!00000001")

    async with session_factory() as session:
        repo = SqlActivityLogRepository(session)
        # Por pasarela
        by_gw = await repo.list_recent(10, gateway_id="gw-02")
        assert [it["event_id"] for it in by_gw] == ["evt-0002"]
        # Por grupo: el nodo miembro + el evento sin nodo; nunca el ajeno
        by_group = await repo.list_recent(10, group_id=group.id)
        assert {it["event_id"] for it in by_group} == {"evt-0001", "evt-0003"}
        # Búsqueda de texto libre sobre el payload (insensible a mayúsculas)
        by_q = await repo.list_recent(10, q="POSICIÓN")
        assert [it["event_id"] for it in by_q] == ["evt-0002"]


async def test_activity_log_internal_type_filter(session_factory):
    """internal_type extraído a columna (migración 0014): filtro exacto para
    reconstruir traceroutes/vecinos históricos sin excavar JSON (capa Rutas)."""
    async with session_factory() as session, session.begin():
        repo = SqlActivityLogRepository(session)
        e1 = make_envelope(1)
        e1["payload"]["internal_type"] = "TRACEROUTE_APP"
        e1["payload"]["raw"] = {"route": ["!00000002"]}
        e2 = make_envelope(2)
        e2["payload"]["internal_type"] = "NEIGHBORINFO_APP"
        e3 = make_envelope(3)  # sin internal_type (evento no-paquete)
        await repo.add_many([e1, e2, e3])

    async with session_factory() as session:
        repo = SqlActivityLogRepository(session)
        traces = await repo.list_recent(10, internal_type="TRACEROUTE_APP")
        assert [it["event_id"] for it in traces] == ["evt-0001"]
        # El payload conserva el raw completo para reconstruir la ruta
        assert traces[0]["payload"]["raw"]["route"] == ["!00000002"]
        # Sin filtro, todo sigue visible (la columna es aditiva)
        assert len(await repo.list_recent(10)) == 3


async def test_activity_log_prune_keeps_most_recent(session_factory):
    async with session_factory() as session, session.begin():
        repo = SqlActivityLogRepository(session)
        await repo.add_many([make_envelope(i) for i in range(1, 21)])
        pruned = await repo.prune_to(5)
        assert pruned == 15

    async with session_factory() as session:
        repo = SqlActivityLogRepository(session)
        assert await repo.count() == 5
        items = await repo.list_recent(limit=10)
        assert items[0]["event_id"] == "evt-0020"
        assert items[-1]["event_id"] == "evt-0016"


async def test_activity_log_writer_flushes_and_survives_stop(session_factory):
    writer = ActivityLogWriter(session_factory, max_rows=100)
    for i in range(1, 4):
        writer.enqueue(make_envelope(i))
    # stop() sin start(): el vaciado final persiste lo encolado igualmente
    await writer.stop()

    async with session_factory() as session:
        assert await SqlActivityLogRepository(session).count() == 3


async def test_publisher_stores_same_envelope_it_publishes(session_factory):
    published: list[dict] = []
    stored: list[dict] = []
    publisher = ActivityPublisher()

    async def publish(env: dict) -> None:
        published.append(env)

    publisher.attach(publish)
    publisher.attach_store(stored.append)
    await publisher.emit_activity(
        ActivityEvent(source="mesh", severity="info", icon="📊", title="t", node_id="!00000001")
    )
    assert len(published) == 1 and len(stored) == 1
    assert published[0] is stored[0]  # un ÚNICO envelope para WS y BD


# ── Agregados reales (counts) ────────────────────────────────────────────────


async def _seed_alerts(session_factory) -> int:
    """3 alertas activas + 1 resuelta; devuelve el id de un grupo con
    SOLO el nodo !00000001 como miembro."""
    now = datetime.now(timezone.utc)
    ingest = IngestService(session_factory)
    for nid in ("!00000001", "!00000002"):
        await ingest.handle_event(make_event("node.seen", {"node_id": nid}))

    async with session_factory() as session, session.begin():
        rule = await SqlAlertRuleRepository(session).create(
            AlertRule(name="r1", rule_type="low_battery", severity="WARNING")
        )
        repo = SqlAlertRepository(session)

        def alert(subject_type: str, subject_id: str, severity: str, status: str = "firing") -> Alert:
            return Alert(
                rule_id=rule.id or 0,
                rule_name="r1",
                subject_type=subject_type,  # type: ignore[arg-type]
                subject_id=subject_id,
                severity=severity,  # type: ignore[arg-type]
                message="m",
                status=status,  # type: ignore[arg-type]
                fired_at=now,
            )

        a1 = await repo.create(alert("node", "!00000001", "WARNING"))  # dentro del grupo
        await repo.create(alert("node", "!00000002", "CRITICAL"))  # fuera, pero CRITICAL
        await repo.create(alert("gateway", "gw-01", "WARNING"))  # no-nodo: siempre dentro
        resolved = await repo.create(alert("node", "!00000001", "INFO"))
        await repo.resolve(resolved.id or 0, now)
        await repo.acknowledge(a1.id or 0, "test")

        group = await SqlGroupRepository(session).create(Group(name="g-counts"))
        await SqlGroupRepository(session).add_member(group.id or 0, "!00000001")
    return group.id or 0


async def test_alert_counts_global(session_factory):
    await _seed_alerts(session_factory)
    async with session_factory() as session:
        counts = await SqlAlertRepository(session).active_counts()
    assert counts == {"active": 3, "firing": 2, "acknowledged": 1, "critical_active": 1}


async def test_alert_counts_group_scoped_matches_ui_semantics(session_factory):
    """Misma regla que scopeAlertsToGroup: no-nodo dentro, CRITICAL de fuera
    también cuenta; una WARNING de un nodo fuera del grupo NO contaría."""
    group_id = await _seed_alerts(session_factory)
    now = datetime.now(timezone.utc)
    async with session_factory() as session, session.begin():
        # WARNING de un nodo fuera del grupo: debe quedar excluida del conteo
        await SqlAlertRepository(session).create(
            Alert(
                rule_id=1, rule_name="r1", subject_type="node", subject_id="!00000002",
                severity="WARNING", message="m", fired_at=now,
            )
        )
    async with session_factory() as session:
        counts = await SqlAlertRepository(session).active_counts(group_id)
        global_counts = await SqlAlertRepository(session).active_counts()
    assert global_counts["active"] == 4
    assert counts == {"active": 3, "firing": 2, "acknowledged": 1, "critical_active": 1}


async def test_operation_counts_global_and_group(session_factory):
    ingest = IngestService(session_factory)
    for nid in ("!00000001", "!00000002"):
        await ingest.handle_event(make_event("node.seen", {"node_id": nid}))

    async with session_factory() as session, session.begin():
        repo = SqlAdminOperationRepository(session)

        def op(node_id: str, status: str) -> AdminOperation:
            return AdminOperation(
                target_node_id=node_id, gateway_id="gw-01",
                operation_type="metadata.get", params={}, status=status,
            )

        await repo.create(op("!00000001", "pending"))
        await repo.create(op("!00000001", "running"))
        await repo.create(op("!00000002", "queued"))
        await repo.create(op("!00000002", "succeeded"))  # terminal: fuera del conteo

        group = await SqlGroupRepository(session).create(Group(name="g-ops"))
        await SqlGroupRepository(session).add_member(group.id or 0, "!00000001")

    async with session_factory() as session:
        repo = SqlAdminOperationRepository(session)
        assert await repo.active_counts() == {
            "pending": 1, "queued": 1, "running": 1, "active": 3,
        }
        assert await repo.active_counts(group.id) == {
            "pending": 1, "queued": 0, "running": 1, "active": 2,
        }


# ── Coherencia preview/create de lotes ───────────────────────────────────────


async def test_preview_blocks_node_routed_to_deleted_gateway(session_factory):
    """Antes: preview miraba solo nodes.gateway_id y daba por elegible un
    nodo cuya única pasarela estaba eliminada; create lo rechazaba después
    (divergencia). Ahora ambos usan el mismo resolver."""
    now = datetime.now(timezone.utc)
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000001"}))

    async with session_factory() as session, session.begin():
        repo = SqlGatewayRepository(session)
        await repo.configure(
            "gw-test", name="gw", transport_type="usb", connection_params={},
            enabled=True, priority=0, desired_status="connected",
        )
        await repo.soft_delete("gw-test", now)

    batches = BatchService(session_factory, make_settings())
    preview = await batches.preview("metadata.get", {}, BatchScope(node_ids=["!00000001"]))
    assert preview.eligible == []
    assert len(preview.excluded) == 1
    assert any("no enrutable" in b for b in preview.excluded[0].blockers)


async def test_preview_eligible_implies_create_succeeds(session_factory):
    """El contrato del hardening: lo que la simulación declara elegible, la
    ejecución lo acepta — mismo resolver, mismo resultado."""
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000001"}))

    batches = BatchService(session_factory, make_settings())
    preview = await batches.preview("metadata.get", {}, BatchScope(node_ids=["!00000001"]))
    assert [p.node_id for p in preview.eligible] == ["!00000001"]

    batch = await batches.create(
        name="b", operation_type="metadata.get", params={},
        node_ids=[p.node_id for p in preview.eligible], scope_description=None,
    )
    assert batch.node_ids == ["!00000001"]
