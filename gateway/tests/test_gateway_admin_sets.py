"""M1.3: constructores/comparadores de SET y pipeline set+verify del simulador."""

import pytest

from gateway.config import Settings
from gateway.decoder.admin import (
    SET_OPERATIONS,
    build_fixed_position_set,
    build_owner_set,
    compare_fixed_position,
    compare_owner,
)
from gateway.transports.simulated import SimulatedTransport


# ── Constructores y comparadores (puros) ─────────────────────────────────────


def test_build_owner_set_partial_fields():
    msg = build_owner_set({"short_name": "4IEN"})
    assert msg.set_owner.short_name == "4IEN"
    assert msg.set_owner.long_name == ""  # no tocado
    msg = build_owner_set({"long_name": "Repetidor Norte"})
    assert msg.set_owner.long_name == "Repetidor Norte"


def test_compare_owner():
    read = {"shortName": "4IEN", "longName": "Repetidor Norte"}
    assert compare_owner({"short_name": "4IEN"}, read)
    assert compare_owner({"short_name": "4IEN", "long_name": "Repetidor Norte"}, read)
    assert not compare_owner({"short_name": "OTRO"}, read)
    assert not compare_owner({"long_name": "Distinto"}, read)


def test_build_fixed_position_scaling():
    msg = build_fixed_position_set({"latitude": 40.4168, "longitude": -3.7038, "altitude": 657})
    assert msg.set_fixed_position.latitude_i == 404168000
    assert msg.set_fixed_position.longitude_i == -37038000
    assert msg.set_fixed_position.altitude == 657


def test_compare_fixed_position_uses_config_flag():
    assert compare_fixed_position({}, {"position": {"fixedPosition": True}})
    assert not compare_fixed_position({}, {"position": {"fixedPosition": False}})
    assert not compare_fixed_position({}, {"position": {}})
    assert not compare_fixed_position({}, {})


def test_set_operations_registry():
    assert {"owner.set", "position.set_fixed", "config.set", "module_config.set"} <= set(
        SET_OPERATIONS
    )
    assert SET_OPERATIONS["owner.set"].verify_get({}) == ("nodeinfo.get", {})
    assert SET_OPERATIONS["position.set_fixed"].verify_get({}) == (
        "config.get", {"section": "position"},
    )
    assert SET_OPERATIONS["config.set"].verify_get({"section": "lora"}) == (
        "config.get", {"section": "lora"},
    )
    assert SET_OPERATIONS["module_config.set"].verify_get({"section": "mqtt"}) == (
        "module_config.get", {"section": "mqtt"},
    )


# ── Simulador: SET + verify de extremo a extremo ─────────────────────────────


class StubRng:
    def uniform(self, a, b):  # noqa: ARG002
        return 0.0

    def random(self):
        return 0.99

    def randint(self, a, b):  # noqa: ARG002
        return a


def make_sim() -> SimulatedTransport:
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    sim = SimulatedTransport(
        emit, Settings(_env_file=None, transport="simulated", sim_node_count=3, sim_seed=11)
    )
    for node in sim._nodes:
        node.rng = StubRng()
    return sim


def op(sim, op_type, params):
    return {
        "operation_id": 1,
        "operation_type": op_type,
        "params": params,
        "timeout_seconds": 10,
        "target_node_id": sim._nodes[0].node_id,
    }


async def test_sim_owner_set_verify_confirmed_and_audit_trail():
    sim = make_sim()
    original_short = sim._nodes[0].short_name
    result = await sim.execute_admin(op(sim, "owner.set", {"short_name": "NEW1", "long_name": "Renombrado"}))

    assert result["verify"] == "confirmed"
    assert result["previous"]["shortName"] == original_short  # valor anterior auditado
    assert result["requested"] == {"short_name": "NEW1", "long_name": "Renombrado"}
    assert result["verified"]["shortName"] == "NEW1"
    # El cambio es real: un GET posterior lo refleja
    read = await sim.execute_admin(op(sim, "nodeinfo.get", {}))
    assert read["shortName"] == "NEW1" and read["longName"] == "Renombrado"


async def test_sim_fixed_position_set_verify_confirmed():
    sim = make_sim()
    result = await sim.execute_admin(
        op(sim, "position.set_fixed", {"latitude": 41.0, "longitude": -3.5, "altitude": 900})
    )
    assert result["verify"] == "confirmed"
    assert result["previous"] == {"position": {"fixedPosition": False}}
    assert sim._nodes[0].lat == 41.0 and sim._nodes[0].lon == -3.5
    assert sim._nodes[0].fixed_position is True


async def test_sim_set_unknown_node_times_out():
    sim = make_sim()
    operation = op(sim, "owner.set", {"short_name": "XX"})
    operation["target_node_id"] = "!ffffffff"
    with pytest.raises(TimeoutError):
        await sim.execute_admin(operation)
