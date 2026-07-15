import uuid
from datetime import datetime, timedelta, timezone

from noc.adapters.notifications.ntfy import build_headers
from noc.adapters.notifications.webhook import build_payload
from noc.adapters.persistence.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from noc.application.alerting.engine import AlertEngine, AlertTransition
from noc.application.alerting.evaluators import EVALUATORS, NetworkSnapshot
from noc.application.alerting.message import render_message
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
    from noc.application.alerting.seed import default_rules

    for rule in default_rules(Settings(_env_file=None)):
        assert rule.rule_type in EVALUATORS


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


# ── Motor de reglas §1: evaluadores nuevos (puros, sin BD) ───────────────────


def _summary(node_id: str, **kwargs):
    from noc.domain.nodes.entities import Node, NodeSummary, Position, Telemetry

    now = datetime.now(timezone.utc)
    tel_fields = {"temperature_c", "channel_utilization", "battery_level"}
    tel_kwargs = {k: v for k, v in kwargs.items() if k in tel_fields}
    node_kwargs = {k: v for k, v in kwargs.items() if k not in tel_fields and k not in ("position_age_s", "group_ids")}
    node = Node(node_id=node_id, last_seen_at=kwargs.get("last_seen_at", now), **{k: v for k, v in node_kwargs.items() if k != "last_seen_at"})
    pos = None
    if "position_age_s" in kwargs:
        pos = Position(node_id=node_id, latitude=0, longitude=0, received_at=now - timedelta(seconds=kwargs["position_age_s"]))
    return NodeSummary(
        node=node,
        last_device_telemetry=Telemetry(node_id=node_id, kind="device", **tel_kwargs) if tel_kwargs else None,
        last_position=pos,
        group_ids=kwargs.get("group_ids", []),
    )


def test_temperature_and_channel_evaluators_pure():
    snap = NetworkSnapshot(
        summaries=[
            _summary("!00000001", temperature_c=52.0, channel_utilization=10.0),
            _summary("!00000002", temperature_c=30.0, channel_utilization=40.0),
            _summary("!00000003"),  # sin telemetría: nunca dispara
        ]
    )
    hot = EVALUATORS["temperature_high"](
        AlertRule(id=1, name="t", rule_type="temperature_high", severity="WARNING", threshold=45), snap
    )
    assert [c.subject_id for c in hot] == ["!00000001"]
    busy = EVALUATORS["channel_utilization_high"](
        AlertRule(id=2, name="c", rule_type="channel_utilization_high", severity="WARNING", threshold=25), snap
    )
    assert [c.subject_id for c in busy] == ["!00000002"]


def test_position_lost_requires_online_and_baseline():
    now = datetime.now(timezone.utc)
    snap = NetworkSnapshot(
        summaries=[
            _summary("!00000001", position_age_s=3 * 3600),  # online, posición vieja -> dispara
            _summary("!00000002"),  # sin GPS: sin línea base, nunca dispara
            _summary("!00000003", position_age_s=3 * 3600, last_seen_at=now - timedelta(hours=5)),  # offline: lo cubre node_offline
        ]
    )
    rule = AlertRule(id=1, name="p", rule_type="position_lost", severity="INFO", duration_seconds=7200)
    assert [c.subject_id for c in EVALUATORS["position_lost"](rule, snap)] == ["!00000001"]


def test_neighbor_link_lost_aggregates_per_node():
    from noc.domain.nodes.entities import NodeNeighbor

    now = datetime.now(timezone.utc)
    snap = NetworkSnapshot(
        summaries=[_summary("!00000001", short_name="UNO"), _summary("!00000002", short_name="DOS")],
        neighbors=[
            NodeNeighbor("!00000001", "!00000002", received_at=now - timedelta(hours=5)),
            NodeNeighbor("!00000001", "!000000ff", received_at=now - timedelta(hours=6)),
            NodeNeighbor("!00000002", "!00000001", received_at=now - timedelta(minutes=5)),  # vivo
        ],
    )
    rule = AlertRule(id=1, name="n", rule_type="neighbor_link_lost", severity="INFO", duration_seconds=7200)
    conds = EVALUATORS["neighbor_link_lost"](rule, snap)
    # Una sola alerta para !00000001 con sus DOS enlaces perdidos agregados
    assert len(conds) == 1
    assert conds[0].subject_id == "!00000001"
    assert "DOS" in conds[0].message and "!000000ff" in conds[0].message


def test_gateway_no_traffic_only_when_connected_with_baseline():
    from noc.domain.nodes.entities import GatewayInfo, NodeGatewayLink

    now = datetime.now(timezone.utc)
    snap = NetworkSnapshot(
        gateways=[
            GatewayInfo(gateway_id="gw-01", status="connected", transport="usb", updated_at=now),
            GatewayInfo(gateway_id="gw-02", status="disconnected", transport="usb", updated_at=now),
            GatewayInfo(gateway_id="gw-03", status="connected", transport="tcp", updated_at=now),
        ],
        links=[
            NodeGatewayLink("!00000001", "gw-01", last_heard_at=now - timedelta(hours=2)),  # sorda
            NodeGatewayLink("!00000002", "gw-02", last_heard_at=now - timedelta(hours=2)),  # desconectada: la cubre gateway_disconnected
            # gw-03 sin enlaces: sin línea base, no dispara
        ],
    )
    rule = AlertRule(id=1, name="g", rule_type="gateway_no_traffic", severity="WARNING", duration_seconds=1800)
    conds = EVALUATORS["gateway_no_traffic"](rule, snap)
    assert [c.subject_id for c in conds] == ["gw-01"]


def test_low_redundancy_needs_two_gateways():
    from noc.domain.nodes.entities import GatewayInfo, NodeGatewayLink

    now = datetime.now(timezone.utc)
    rule = AlertRule(id=1, name="r", rule_type="low_redundancy", severity="INFO", threshold=50)
    one_gw = NetworkSnapshot(
        summaries=[_summary("!00000001")],
        gateways=[GatewayInfo(gateway_id="gw-01", status="connected", transport="usb", updated_at=now)],
        links=[NodeGatewayLink("!00000001", "gw-01", last_heard_at=now)],
    )
    # Mono-pasarela: redundancia 0 % es lo normal, nunca dispara
    assert EVALUATORS["low_redundancy"](rule, one_gw) == []

    two_gw = NetworkSnapshot(
        summaries=[_summary("!00000001"), _summary("!00000002")],
        gateways=[
            GatewayInfo(gateway_id="gw-01", status="connected", transport="usb", updated_at=now),
            GatewayInfo(gateway_id="gw-02", status="connected", transport="tcp", updated_at=now),
        ],
        # Solo 1 de 2 nodos con doble cobertura -> 50 % < umbral 60
        links=[
            NodeGatewayLink("!00000001", "gw-01", last_heard_at=now),
            NodeGatewayLink("!00000001", "gw-02", last_heard_at=now),
            NodeGatewayLink("!00000002", "gw-01", last_heard_at=now),
        ],
    )
    rule60 = AlertRule(id=1, name="r", rule_type="low_redundancy", severity="INFO", threshold=60)
    conds = EVALUATORS["low_redundancy"](rule60, two_gw)
    assert len(conds) == 1
    assert conds[0].subject_type == "system"
    assert conds[0].correlation_key == "system:redundancy"


def test_group_scoped_snapshot_filters_members():
    snap = NetworkSnapshot(
        summaries=[
            _summary("!00000001", battery_level=5, group_ids=[7]),
            _summary("!00000002", battery_level=5),  # fuera del grupo
        ]
    )
    rule = AlertRule(id=1, name="b", rule_type="low_battery", severity="WARNING", threshold=20, group_id=7)
    conds = EVALUATORS["low_battery"](rule, snap.scoped_to_group(7))
    assert [c.subject_id for c in conds] == ["!00000001"]
    # El mismo snapshot sin escopar dispara para ambos (regla global)
    assert len(EVALUATORS["low_battery"](AlertRule(id=2, name="b2", rule_type="low_battery", severity="WARNING", threshold=20), snap)) == 2


async def test_group_rule_end_to_end(session_factory):
    """Regla por grupo en el engine real: solo alerta a los miembros."""
    from noc.adapters.persistence.organization_repositories import SqlGroupRepository
    from noc.domain.nodes.entities import Group

    await seed_network(session_factory)  # !00000002 tiene batería 8
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000004", "short_name": "G4"}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000004", "kind": "device", "battery_level": 3})
    )
    async with session_factory() as session, session.begin():
        group = await SqlGroupRepository(session).create(Group(name="críticos"))
        await SqlGroupRepository(session).add_member(group.id or 0, "!00000004")
        await SqlAlertRuleRepository(session).create(
            AlertRule(
                name="Batería baja · críticos",
                rule_type="low_battery",
                severity="CRITICAL",
                threshold=50,
                group_id=group.id,
            )
        )

    engine = AlertEngine(session_factory)
    transitions = await engine.evaluate_once()
    scoped = [t for t in transitions if t.kind == "fired" and t.alert.rule_name == "Batería baja · críticos"]
    # Umbral 50: dispararía para !00000002 (8 %) y !00000004 (3 %) si fuera
    # global — escopada al grupo solo alerta al miembro
    assert [t.alert.subject_id for t in scoped] == ["!00000004"]
    assert scoped[0].alert.severity == "CRITICAL"


async def test_seed_is_incremental_by_rule_type(session_factory):
    """Instalación existente: los tipos nuevos se siembran sin tocar los que
    el operador ya ajustó."""
    settings = Settings(_env_file=None)
    async with session_factory() as session, session.begin():
        repo = SqlAlertRuleRepository(session)
        await repo.create(
            AlertRule(name="Mi batería", rule_type="low_battery", severity="CRITICAL", threshold=42)
        )

    await seed_default_rules(session_factory, settings)

    async with session_factory() as session:
        rules = await SqlAlertRuleRepository(session).list_all()
    by_type = {r.rule_type: r for r in rules}
    # La regla del operador queda intacta (no se duplica su tipo)
    assert by_type["low_battery"].name == "Mi batería"
    assert by_type["low_battery"].threshold == 42
    # Y todos los demás tipos por defecto aparecen
    from noc.application.alerting.seed import default_rules

    assert {r.rule_type for r in default_rules(settings)} <= set(by_type)


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
    payload = build_payload(render_message(alert, "fired"))
    assert payload["event"] == "alert.fired"
    assert payload["alert"]["severity"] == "WARNING"
    assert payload["alert"]["subject"] == "node:!00000002"
    assert payload["source"] == "meshtastic-noc"


def test_ntfy_priority_mapping():
    alert = Alert(
        rule_id=1, rule_name="R", subject_type="node", subject_id="!00000001",
        severity="CRITICAL", message="m",
    )
    assert build_headers(render_message(alert, "fired"))["Priority"] == "5"
    assert build_headers(render_message(alert, "resolved"))["Priority"] == "3"
    alert.severity = "INFO"
    assert build_headers(render_message(alert, "fired"))["Priority"] == "2"
