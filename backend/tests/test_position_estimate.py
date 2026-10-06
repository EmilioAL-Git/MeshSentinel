from datetime import datetime, timedelta, timezone

from noc.application.position_estimate import Anchor, compute_estimates, estimate_position
from noc.application.rf_graph import RfEdge, haversine_m
from noc.domain.nodes.entities import GatewayInfo, Node, NodeGatewayLink, NodeSummary, Position

NOW = datetime.now(timezone.utc)


def _s(node_id: str, pos: tuple[float, float] | None = None) -> NodeSummary:
    return NodeSummary(
        node=Node(node_id=node_id, last_seen_at=NOW),
        last_position=Position(node_id, pos[0], pos[1], received_at=NOW) if pos else None,
    )


def test_single_anchor_gives_wide_radius_and_more_anchors_tighten_it():
    one = estimate_position("!x", [Anchor(40.0, -2.0, 5.0, 1.0, "gateway")])
    assert one and one.radius_m == 5000 and (one.latitude, one.longitude) == (40.0, -2.0)
    four = estimate_position("!x", [Anchor(40.0, -2.0, 5.0, 1.0, "link")] * 4)
    assert four and four.radius_m < one.radius_m


def test_weights_pull_towards_strong_recent_anchor():
    est = estimate_position(
        "!x", [Anchor(40.00, -2.0, 8.0, 1.0, "link"), Anchor(40.04, -2.0, -15.0, 40.0, "link")]
    )
    assert est and est.latitude < 40.02  # más cerca del ancla fuerte y reciente


def test_divergent_anchors_give_no_estimate():
    assert estimate_position("!x", [Anchor(40.0, -2.0, 5, 1, "link"), Anchor(45.0, 3.0, 5, 1, "link")]) is None


def test_only_direct_gateway_links_anchor_and_real_position_wins():
    gw = GatewayInfo(gateway_id="gw-1", status="connected", transport="usb", local_node_id="!gw000001")
    summaries = [_s("!gw000001", (40.0, -2.0)), _s("!direct01"), _s("!far00001"), _s("!hasgps01", (41.0, -3.0))]
    links = [
        NodeGatewayLink("!direct01", "gw-1", snr=6.0, hops_away=0, last_heard_at=NOW),
        NodeGatewayLink("!far00001", "gw-1", snr=6.0, hops_away=4, last_heard_at=NOW),  # lejos: no ancla
        NodeGatewayLink("!hasgps01", "gw-1", snr=6.0, hops_away=0, last_heard_at=NOW),  # ya tiene GPS
        NodeGatewayLink("!direct01", "gw-1", snr=6.0, hops_away=0, last_heard_at=NOW - timedelta(days=5)),
    ]
    out = compute_estimates(summaries, links, [gw], [], NOW)
    assert set(out) == {"!direct01"}
    assert out["!direct01"].anchors == 1


def test_rf_edges_with_positioned_nodes_anchor_in_both_directions():
    summaries = [_s("!aaaaaaa1", (40.0, -2.0)), _s("!bbbbbbb2")]
    edges = [RfEdge("!bbbbbbb2", "!aaaaaaa1", 4.0, NOW, "neighbor")]
    out = compute_estimates(summaries, [], [], edges, NOW)
    assert "!bbbbbbb2" in out
    assert haversine_m(out["!bbbbbbb2"].latitude, out["!bbbbbbb2"].longitude, 40.0, -2.0) < 1


async def test_service_replaces_rows_and_drops_stale(session_factory):
    from sqlalchemy import select

    from noc.adapters.persistence.models import EstimatedPositionModel
    from noc.application.position_estimation import PositionEstimationService

    est = {}
    async with session_factory() as s, s.begin():
        s.add(EstimatedPositionModel(node_id="!old00001", latitude=1, longitude=1, radius_m=5000, anchors=1, computed_at=NOW))
    from noc.application.position_estimate import Estimate

    est["!new00001"] = Estimate("!new00001", 40.0, -2.0, 800, 3)
    async with session_factory() as s, s.begin():
        await PositionEstimationService._replace(s, est, NOW)
    async with session_factory() as s:
        ids = (await s.scalars(select(EstimatedPositionModel.node_id))).all()
    assert ids == ["!new00001"]
