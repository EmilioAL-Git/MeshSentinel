from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from noc.application.delivery import build_delivery_diagnostic
from noc.domain.chat.entities import ChatMessage

NOW = datetime.now(timezone.utc)


def _msg(id_: int, gw: str, packet_id: int | None = 77, **kw) -> ChatMessage:
    base = dict(
        id=id_, from_node_id="!00000001", to_node_id=None, text="hola", gateway_id=gw,
        packet_id=packet_id, received_at=NOW, snr=5.0, rssi=-90, hop_limit=2, hop_start=3,
    )
    base.update(kw)
    return ChatMessage(**base)


def test_groups_gateways_and_labels_provenance():
    a, b = _msg(1, "gw-a"), _msg(2, "gw-b", snr=-3.5, hop_limit=3, hop_start=3)
    other_packet = _msg(3, "gw-c", packet_id=99)
    old_reuse = _msg(4, "gw-d", received_at=NOW - timedelta(hours=3))  # packet_id reutilizado
    diag = build_delivery_diagnostic(a, [a, b, other_packet, old_reuse])
    assert [h.gateway_id for h in diag.heard_by] == ["gw-a", "gw-b"]
    assert diag.heard_by_count == 2
    first = diag.heard_by[0]
    assert first.snr.provenance == "observed" and first.hop_limit.provenance == "reported"
    assert first.hops_used.value == 1 and first.hops_used.provenance == "inferred"
    assert diag.heard_by[1].hops_used.value == 0
    assert diag.to_node_id.value == "difusión" and diag.to_node_id.provenance == "inferred"


def test_unknowns_are_never_invented():
    legacy = _msg(1, "gw-a", hop_start=0, rssi=None)
    diag = build_delivery_diagnostic(legacy, [legacy])
    h = diag.heard_by[0]
    assert h.hops_used.value is None and h.hops_used.provenance == "unknown"
    assert h.rssi.provenance == "unknown"


def test_without_packet_id_only_own_row():
    m = _msg(1, "gw-a", packet_id=None)
    diag = build_delivery_diagnostic(m, [m, _msg(2, "gw-b", packet_id=None)])
    assert diag.heard_by_count == 1 and diag.packet_id.provenance == "unknown"
    assert any("packet_id" in n for n in diag.notes)
    assert asdict(diag)["heard_by"][0]["gateway_id"] == "gw-a"
