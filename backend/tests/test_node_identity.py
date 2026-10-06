import base64
import zlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from noc.adapters.persistence.identity_merge import merge_identity
from noc.adapters.persistence.models import (
    GroupMemberModel,
    GroupModel,
    NodeModel,
    NodeTagModel,
    PositionModel,
    TagModel,
    TelemetryModel,
)
from noc.application.alerting.evaluators import EVALUATORS, NetworkSnapshot
from noc.application.node_identity import (
    find_duplicate_keys,
    find_weak_keys,
    key_bytes,
    node_num_from_key,
    pair_identity_changes,
    superseded_node_ids,
)
from noc.domain.alerts.entities import AlertRule
from noc.domain.nodes.entities import Node, NodeSummary

NOW = datetime.now(timezone.utc)


def _key(seed: int) -> str:
    raw = bytes((seed * 7 + i * 13 + (i * i) % 251) % 256 for i in range(32))
    return base64.b64encode(raw).decode()


def _node(node_id: str, key: str | None = None, num: int | None = None, **kw) -> Node:
    return Node(node_id=node_id, node_num=num, public_key=key, **kw)


def _canonical(key: str, **kw) -> Node:
    num = node_num_from_key(key_bytes(key))
    return _node(f"!{num:08x}", key, num, **kw)


def test_node_num_is_crc32_of_key():
    k = _key(1)
    assert node_num_from_key(key_bytes(k)) == zlib.crc32(base64.b64decode(k)) & 0xFFFFFFFF


def test_key_bytes_rejects_bad_input():
    assert key_bytes(None) is None
    assert key_bytes("no-es-base64!") is None
    assert key_bytes(base64.b64encode(b"corta").decode()) is None


def test_pairs_old_identity_with_derived_successor():
    k = _key(1)
    old = _node("!aaaa0001", k, 0xAAAA0001, last_seen_at=NOW - timedelta(days=2), first_seen_at=NOW - timedelta(days=60))
    new = _canonical(k, first_seen_at=NOW - timedelta(days=1), last_seen_at=NOW)
    changes = pair_identity_changes([old, new])
    assert [(c.predecessor_id, c.successor_id, c.basis) for c in changes] == [(old.node_id, new.node_id, "same_key")]
    assert changes[0].predecessor_quiet is True
    assert superseded_node_ids(changes) == {old.node_id}


def test_key_mismatch_vetoes_even_with_same_name():
    k, other = _key(1), _key(2)
    old = _node("!aaaa0001", k, 0xAAAA0001, short_name="SAME")
    new = _node(f"!{node_num_from_key(key_bytes(k)):08x}", other, node_num_from_key(key_bytes(k)), short_name="SAME")
    assert pair_identity_changes([old, new]) == []


def test_successor_without_key_pairs_by_derived_num():
    k = _key(3)
    num = node_num_from_key(key_bytes(k))
    old = _node("!aaaa0001", k, 0xAAAA0001)
    new = _node(f"!{num:08x}", None, num)  # aún no ha anunciado su clave
    changes = pair_identity_changes([old, new])
    assert len(changes) == 1 and changes[0].basis == "derived_num"


def test_canonical_node_alone_is_not_a_change():
    assert pair_identity_changes([_canonical(_key(4))]) == []


def test_duplicates_exclude_identity_changes():
    k = _key(5)
    old, new = _node("!aaaa0001", k, 0xAAAA0001), _canonical(k)
    assert find_duplicate_keys([old, new], pair_identity_changes([old, new])) == []

    # Dos nodos con número "libre" y la misma clave: clonado → duplicado real
    a, b = _node("!aaaa0001", _key(6), 0xAAAA0001), _node("!bbbb0002", _key(6), 0xBBBB0002)
    groups = find_duplicate_keys([a, b], pair_identity_changes([a, b]))
    assert len(groups) == 1 and groups[0].node_ids == ["!aaaa0001", "!bbbb0002"]


def test_weak_keys_structural():
    zeros = base64.b64encode(bytes(32)).decode()
    repeated = base64.b64encode(bytes([1, 2, 3, 4] * 8)).decode()
    sequential = base64.b64encode(bytes(range(32))).decode()
    few = base64.b64encode(bytes([i % 5 for i in range(32)])).decode()
    nodes = [
        _node("!00000001", zeros), _node("!00000002", repeated), _node("!00000003", sequential),
        _node("!00000004", few), _node("!00000005", _key(7)),
    ]
    weak = {w.node_id for w in find_weak_keys(nodes)}
    assert weak == {"!00000001", "!00000002", "!00000003", "!00000004"}


def _summary(node: Node) -> NodeSummary:
    return NodeSummary(node=node)


def test_node_offline_ignores_superseded_and_key_security_rule():
    k = _key(8)
    old = _node("!aaaa0001", k, 0xAAAA0001, short_name="VIEJO", last_seen_at=NOW - timedelta(days=3))
    new = _canonical(k, short_name="NUEVO", last_seen_at=NOW)
    snap = NetworkSnapshot(
        summaries=[_summary(old), _summary(new)],
        superseded_ids=frozenset(superseded_node_ids(pair_identity_changes([old, new]))),
        all_nodes=[old, new],
    )
    rule = AlertRule(id=1, name="o", rule_type="node_offline", severity="WARNING", duration_seconds=1800)
    assert EVALUATORS["node_offline"](rule, snap) == []  # el viejo ya tiene sucesor
    sec = AlertRule(id=2, name="k", rule_type="key_security", severity="WARNING")
    assert EVALUATORS["key_security"](sec, snap) == []  # y no cuenta como clave duplicada


def test_key_security_flags_duplicates_and_weak():
    a = _node("!aaaa0001", _key(9), 0xAAAA0001, short_name="A")
    b = _node("!bbbb0002", _key(9), 0xBBBB0002, short_name="B")
    w = _node("!cccc0003", base64.b64encode(bytes(32)).decode(), 0xCCCC0003, short_name="W")
    snap = NetworkSnapshot(summaries=[_summary(a), _summary(b), _summary(w)], all_nodes=[a, b, w])
    rule = AlertRule(id=2, name="k", rule_type="key_security", severity="WARNING")
    conds = {c.subject_id: c.message for c in EVALUATORS["key_security"](rule, snap)}
    assert set(conds) == {"!aaaa0001", "!bbbb0002", "!cccc0003"}
    assert "duplicada" in conds["!aaaa0001"] and "débil" in conds["!cccc0003"]


async def test_merge_moves_history_and_deletes_old(session_factory):
    old_id, new_id = "!aaaa0001", "!bbbb0002"
    async with session_factory() as s, s.begin():
        for nid, fav in ((old_id, True), (new_id, False)):
            s.add(NodeModel(id=nid, first_seen_at=NOW - timedelta(days=5 if nid == old_id else 1), last_seen_at=NOW, is_favorite=fav))
        s.add(TagModel(id=1, name="t"))
        s.add(GroupModel(id=1, name="g"))
        await s.flush()
        s.add_all([NodeTagModel(node_id=old_id, tag_id=1), NodeTagModel(node_id=new_id, tag_id=1)])  # choque de PK
        s.add(GroupMemberModel(group_id=1, node_id=old_id))
        s.add(PositionModel(node_id=old_id, latitude=1.0, longitude=2.0, received_at=NOW))
        s.add(TelemetryModel(node_id=old_id, kind="device", received_at=NOW))
    async with session_factory() as s, s.begin():
        moved = await merge_identity(s, old_id, new_id)
    assert moved["positions"] == 1 and moved["telemetry"] == 1 and moved["groups"] == 1
    async with session_factory() as s:
        assert await s.get(NodeModel, old_id) is None
        new = await s.get(NodeModel, new_id)
        assert new.is_favorite is True  # heredado
        assert (await s.scalars(select(PositionModel.node_id))).all() == [new_id]
        assert (await s.scalars(select(NodeTagModel.node_id))).all() == [new_id]  # sin duplicar
        assert (await s.scalars(select(GroupMemberModel.node_id))).all() == [new_id]


# ── Informe de problemas, fase 1 ─────────────────────────────────────────────


def _rule(rule_type: str, **kw) -> AlertRule:
    return AlertRule(id=1, name=rule_type, rule_type=rule_type, severity="WARNING", **kw)


def test_problem_report_phase1_evaluators():
    from noc.domain.nodes.entities import Telemetry

    hot = Node(node_id="!00000001", short_name="HOT", role="ROUTER_CLIENT", last_seen_at=NOW)
    calm = Node(node_id="!00000003", short_name="OK", role="CLIENT", last_seen_at=NOW)
    summaries = [
        NodeSummary(node=hot, last_device_telemetry=Telemetry("!00000001", "device", air_util_tx=11.0)),
        NodeSummary(
            node=calm,
            last_device_telemetry=Telemetry("!00000003", "device", air_util_tx=1.0),
        ),
    ]
    snap = NetworkSnapshot(
        summaries=summaries,
        position_counts_1h={"!00000001": 40, "!00000003": 4},
        telemetry_counts_1h={"!00000003": 30},
        now=NOW,
    )

    def ids(rule_type: str, **kw):
        return [c.subject_id for c in EVALUATORS[rule_type](_rule(rule_type, **kw), snap)]

    assert ids("chatty_node") == ["!00000001"]
    assert ids("obsolete_role") == ["!00000001"]
    assert ids("position_overbroadcast") == ["!00000001"]
    assert ids("telemetry_overbroadcast") == ["!00000003"]
    assert ids("position_overbroadcast", threshold=100) == []  # umbral editable


def test_duplicate_alert_hints_same_device_when_names_match():
    a = _node("!aaaa0001", _key(11), 0xAAAA0001, short_name="LDVN", long_name="Ladvan")
    b = _node("!bbbb0002", _key(11), 0xBBBB0002, short_name="LDVN", long_name="Ladvan")
    c = _node("!cccc0003", _key(12), 0xCCCC0003, short_name="X", long_name="Uno")
    d = _node("!dddd0004", _key(12), 0xDDDD0004, short_name="Y", long_name="Otro")
    snap = NetworkSnapshot(summaries=[_summary(n) for n in (a, b, c, d)], all_nodes=[a, b, c, d])
    conds = {x.subject_id: x.message for x in EVALUATORS["key_security"](_rule("key_security"), snap)}
    assert "mismo nombre" in conds["!aaaa0001"]
    assert "mismo nombre" not in conds["!cccc0003"]
