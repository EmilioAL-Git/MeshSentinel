"""Traceroute activo (`traceroute.run`): resultado de la operación admin."""

import asyncio

from gateway.config import Settings
from gateway.decoder.meshtastic import traceroute_result
from gateway.transports.simulated import SimulatedTransport
from gateway.transports.usb import MeshtasticUsbTransport

A, B = 0xA1B2C3D4, 0xB2A7C3A8


def reply(route=(), back=(), towards=(20,), snr_back=(-6,)):
    return {
        "from": B,
        "decoded": {
            "portnum": "TRACEROUTE_APP",
            "traceroute": {
                "route": list(route),
                "routeBack": list(back),
                "snrTowards": list(towards),
                "snrBack": list(snr_back),
            },
        },
    }


def test_result_direct_route_has_empty_hops_and_snr_in_db():
    r = traceroute_result(reply())
    assert r == {
        "reached": True,
        "route": [],
        "snr_towards": [5.0],
        "route_back": [],
        "snr_back": [-1.5],
    }


def test_result_with_hops_and_unknown_snr():
    r = traceroute_result(reply(route=[A], back=[A], towards=[8, -128], snr_back=[4, 4]))
    assert r["route"] == ["!a1b2c3d4"] and r["route_back"] == ["!a1b2c3d4"]
    assert r["snr_towards"] == [2.0, None]


def test_routing_nak_is_a_result_not_an_error():
    r = traceroute_result({"decoded": {"portnum": "ROUTING_APP", "routing": {"errorReason": "NO_ROUTE"}}})
    assert r == {"reached": False, "error_reason": "NO_ROUTE"}


class FakeIface:
    def __init__(self, response=None):
        self.response, self.calls = response, []

    def sendData(self, data, **kw):  # noqa: N802
        self.calls.append(kw)
        if self.response is not None:
            kw["onResponse"](self.response)


def make(response):
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    t = MeshtasticUsbTransport(emit, Settings(_env_file=None, transport="usb"))
    t._iface = FakeIface(response)
    t._loop = asyncio.get_running_loop()
    return t


async def test_execute_returns_route_and_sends_single_flood_with_hop_limit():
    t = make(reply(route=[A]))
    out = await t._execute_traceroute("!b2a7c3a8", {"hop_limit": 3}, {"timeout_seconds": 60})
    assert out["reached"] is True and out["route"] == ["!a1b2c3d4"]
    assert len(t._iface.calls) == 1 and t._iface.calls[0]["hopLimit"] == 3
    assert t._iface.calls[0]["wantResponse"] is True


async def test_no_response_is_a_result_not_a_timeout(monkeypatch):
    t = make(None)
    real_wait_for = asyncio.wait_for

    async def fast(fut, timeout):  # no esperar 28 s reales
        return await real_wait_for(fut, timeout=0.05)

    monkeypatch.setattr("gateway.transports.meshtastic_stream.asyncio.wait_for", fast)
    out = await t._execute_traceroute("!b2a7c3a8", {}, {"timeout_seconds": 120})
    assert out["reached"] is False and out["error_reason"] == "NO_RESPONSE"
    assert len(t._iface.calls) == 1  # nunca reenvía por su cuenta


async def test_simulator_supports_traceroute():
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    sim = SimulatedTransport(emit, Settings(_env_file=None, transport="simulated", sim_node_count=3, sim_seed=5))
    sim._nodes  # noqa: B018 - la malla se construye en el constructor
    node = next(n for n in sim._nodes if n.node_id != getattr(sim, "_local_id", ""))
    outs = []
    for _ in range(6):
        try:
            outs.append(await sim.execute_admin({"target_node_id": node.node_id, "operation_type": "traceroute.run", "params": {}}))
        except TimeoutError:
            pass  # el simulador pierde ~10 % de peticiones a propósito
    assert outs and all(o["reached"] is True and "route" in o for o in outs)
