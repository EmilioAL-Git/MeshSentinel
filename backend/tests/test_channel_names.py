from noc.application.channel_names import merge_channel_names
from noc.domain.nodes.entities import GatewayInfo


def _gw(gateway_id: str, priority: int, channels: list[dict]) -> GatewayInfo:
    return GatewayInfo(
        gateway_id=gateway_id,
        status="connected",
        transport="usb",
        priority=priority,
        channels=channels,
    )


def test_merge_prefers_higher_priority_gateway():
    gateways = [
        _gw("gw-02", 0, [{"index": 0, "name": "FromGw02"}]),
        _gw("gw-01", 1, [{"index": 0, "name": "FromGw01"}]),
    ]
    assert merge_channel_names(gateways) == {0: "FromGw01"}


def test_merge_ties_broken_by_gateway_id_ascending():
    gateways = [
        _gw("gw-02", 0, [{"index": 0, "name": "FromGw02"}]),
        _gw("gw-01", 0, [{"index": 0, "name": "FromGw01"}]),
    ]
    assert merge_channel_names(gateways) == {0: "FromGw01"}


def test_merge_fills_gaps_from_other_gateways():
    gateways = [
        _gw("gw-01", 1, [{"index": 0, "name": "Iberia"}]),
        _gw("gw-02", 0, [{"index": 0, "name": "Ignored"}, {"index": 2, "name": "Nexus"}]),
    ]
    assert merge_channel_names(gateways) == {0: "Iberia", 2: "Nexus"}


def test_merge_skips_empty_names_and_missing_index():
    gateways = [
        _gw("gw-01", 0, [{"index": 0, "name": ""}, {"name": "NoIndex"}, {"index": 1, "name": " "}]),
    ]
    assert merge_channel_names(gateways) == {}


def test_merge_with_no_gateways_is_empty():
    assert merge_channel_names([]) == {}
