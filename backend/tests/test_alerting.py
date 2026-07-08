import uuid
from datetime import datetime, timedelta, timezone

from noc.adapters.notifications.ntfy import build_headers
from noc.adapters.notifications.webhook import build_payload
from noc.adapters.persistence.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from noc.application.alerting.engine import AlertEngine, AlertTransition
from noc.application.alerting.evaluators import EVALUATORS, NetworkSnapshot
from noc.application.alerting.seed import seed_default_rules
from noc.application.ingest import IngestService
from noc.config import Settings
from noc.domain.alerts.entities import Alert, AlertRule


def make_event(event_type: str, payload: dict, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


async def seed_network(session_factory) -> None:
    ingest = IngestService(session_factory)
    now = datetime.now(timezone.utc)
    await ingest.handle_event(make_event("gateway.status", {"status": "connected", "transport": "simulated"}))
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000001", "short_name": "OK", "snr": 6.0}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000001", "kind": "device", "battery_level": 95})
    )
    # Batería baja
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000002", "short_name": "BAJO"}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000002", "kind": "device", "battery_level": 8})
    )
    # Inactivo 2h
    await ingest.handle_event(
        make_event("node.seen", {"node_id": "!00000003", "short_name": "MUDO"}, now - timedelta(hours=2))
    )


async def setup_engine(session_factory) -> tuple[AlertEngine, list[AlertTransition]]:
    await seed_default_rules(session_factory, Settings(_env_file=None))
    engine = AlertEngine(session_factory)
    received: list[AlertTransition] = []

    async def listener(t: AlertTransition) -> None:
        received.append(t)

    engine.add_listener(listener)
    return engine, received


async def test_fires_resolves_and_deduplicates(session_factory):
    await seed_network(session_factory)
    engine, received = await setup_engine(session_factory)

    transitions = await engine.evaluate_once()
    fired = {(t.alert.rule_name, t.alert.subject_id) for t in transitions if t.kind == "fired"}
    assert ("Batería baja", "!00000002") in fired
    assert ("Nodo sin actividad", "!00000003") in fired
    assert len(received) == len(transitions)

    # Segunda evaluación: mismas condiciones -> ninguna transición nueva
    assert await engine.evaluate_once() == []

    # La batería se recupera -> resolved
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000002", "kind": "device", "battery_level": 80})
    )
    transitions = await engine.evaluate_once()
    resolved = [t for t in transitions if t.kind == "resolved"]
    assert len(resolved) == 1
    assert resolved[0].alert.subject_id == "!00000002"
    assert resolved[0].alert.resolved_at is not None


async def test_severity_propagates_from_rule(session_factory):
    await seed_network(session_factory)
    engine, _ = await setup_engine(session_factory)
    transitions = await engine.evaluate_once()
    by_rule = {t.alert.rule_name: t.alert for t in transitions if t.kind == "fired"}
    assert by_rule["Batería baja"].severity == "WARNING"


async def test_acknowledged_survives_until_condition_clears(session_factory):
    await seed_network(session_factory)
    engine, _ = await setup_engine(session_factory)
    transitions = await engine.evaluate_once()
    alert = next(t.alert for t in transitions if t.alert.rule_name == "Batería baja")

    async with session_factory() as session, session.begin():
        acked = await SqlAlertRepository(session).acknowledge(alert.id, "emilio")
    assert acked is not None and acked.status == "acknowledged"

    # Sigue activa (no se re-dispara ni se duplica) mientras persista la condición
    assert await engine.evaluate_once() == []
    async with session_factory() as session:
        active = await SqlAlertRepository(session).list_active()
    assert any(a.id == alert.id and a.status == "acknowledged" for a in active)

    # Al desaparecer la condición se resuelve también la reconocida
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000002", "kind": "device", "battery_level": 70})
    )
    transitions = await engine.evaluate_once()
    assert any(t.kind == "resolved" and t.alert.id == alert.id for t in transitions)


async def test_gateway_disconnected_rule(session_factory):
    engine, _ = await setup_engine(session_factory)
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("gateway.status", {"status": "disconnected", "transport": "usb"}))
    transitions = await engine.evaluate_once()
    fired = [t for t in transitions if t.kind == "fired"]
    assert len(fired) == 1
    assert fired[0].alert.subject_type == "gateway"
    assert fired[0].alert.severity == "CRITICAL"
    assert fired[0].alert.correlation_key == "gateway:gw-test"


async def test_cooldown_reminder(session_factory):
    await seed_network(session_factory)
    engine, _ = await setup_engine(session_factory)
    # Activar cooldown de 1s en la regla de batería
    async with session_factory() as session, session.begin():
        rules = await SqlAlertRuleRepository(session).list_all()
        battery_rule = next(r for r in rules if r.rule_type == "low_battery")
        await SqlAlertRuleRepository(session).update(battery_rule.id, {"cooldown_seconds": 1})

    await engine.evaluate_once()  # fired
    # Forzar antigüedad del last_notified_at
    async with session_factory() as session, session.begin():
        active = await SqlAlertRepository(session).list_active()
        target = next(a for a in active if a.rule_name == "Batería baja")
        await SqlAlertRepository(session).mark_notified(
            target.id, datetime.now(timezone.utc) - timedelta(seconds=5)
        )
    transitions = await engine.evaluate_once()
    assert any(t.kind == "reminder" for t in transitions)


def test_evaluator_registry_covers_default_rules():
    for rule in ("low_battery", "node_offline", "snr_degraded", "gateway_disconnected"):
        assert rule in EVALUATORS


def test_snr_evaluator_pure():
    from noc.domain.nodes.entities import Node, NodeSummary

    rule = AlertRule(id=1, name="snr", rule_type="snr_degraded", severity="INFO", threshold=-15)
    snap = NetworkSnapshot(
        summaries=[
            NodeSummary(node=Node(node_id="!00000001", snr=-20.0)),
            NodeSummary(node=Node(node_id="!00000002", snr=-5.0)),
            NodeSummary(node=Node(node_id="!00000003", snr=None)),
        ]
    )
    conditions = EVALUATORS["snr_degraded"](rule, snap)
    assert [c.subject_id for c in conditions] == ["!00000001"]


def test_webhook_payload_shape():
    alert = Alert(
        id=7,
        rule_id=1,
        rule_name="Batería baja",
        subject_type="node",
        subject_id="!00000002",
        severity="WARNING",
        message="Batería al 8%",
        fired_at=datetime.now(timezone.utc),
    )
    payload = build_payload(alert, "fired")
    assert payload["event"] == "alert.fired"
    assert payload["alert"]["severity"] == "WARNING"
    assert payload["alert"]["subject_id"] == "!00000002"
    assert payload["source"] == "meshtastic-noc"


def test_ntfy_priority_mapping():
    alert = Alert(
        rule_id=1, rule_name="R", subject_type="node", subject_id="!00000001",
        severity="CRITICAL", message="m",
    )
    assert build_headers(alert, "fired")["Priority"] == "5"
    assert build_headers(alert, "resolved")["Priority"] == "3"
    alert.severity = "INFO"
    assert build_headers(alert, "fired")["Priority"] == "2"
