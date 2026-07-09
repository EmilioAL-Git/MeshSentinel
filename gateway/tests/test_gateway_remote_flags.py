"""M4.1 (ADR 0019): constructores ack-only y ejecución simulada de
favoritos/ignorados/ficha de contacto."""

from gateway.config import Settings
from gateway.decoder.admin import (
    ACK_ONLY_OPERATIONS,
    build_contact_add,
    build_favorite_remove,
    build_favorite_set,
    build_ignored_remove,
    build_ignored_set,
)
from gateway.transports.simulated import SimulatedTransport

SUBJECT = "!0badc0de"
SUBJECT_NUM = 0x0BADC0DE


# ── Constructores (puros) ────────────────────────────────────────────────────


def test_build_favorite_set_and_remove():
    assert build_favorite_set({"subject_node_id": SUBJECT}).set_favorite_node == SUBJECT_NUM
    assert build_favorite_remove({"subject_node_id": SUBJECT}).remove_favorite_node == SUBJECT_NUM


def test_build_ignored_set_and_remove():
    assert build_ignored_set({"subject_node_id": SUBJECT}).set_ignored_node == SUBJECT_NUM
    assert build_ignored_remove({"subject_node_id": SUBJECT}).remove_ignored_node == SUBJECT_NUM


def test_build_contact_add_populates_shared_contact():
    msg = build_contact_add(
        {
            "subject_node_id": SUBJECT,
            "long_name": "Repetidor Norte",
            "short_name": "RNOR",
            "hw_model": "TBEAM",
        }
    )
    assert msg.add_contact.node_num == SUBJECT_NUM
    assert msg.add_contact.user.id == SUBJECT
    assert msg.add_contact.user.long_name == "Repetidor Norte"
    assert msg.add_contact.user.short_name == "RNOR"
    assert msg.add_contact.user.hw_model == 4  # TBEAM en mesh_pb2.HardwareModel


def test_build_contact_add_ignores_unknown_hw_model():
    msg = build_contact_add({"subject_node_id": SUBJECT, "hw_model": "NO_TAL_MODELO"})
    assert msg.add_contact.user.hw_model == 0  # default: no revienta, se omite


def test_ack_only_operations_registry():
    assert {"favorite.set", "favorite.remove", "ignored.set", "ignored.remove", "contact.add"} <= set(
        ACK_ONLY_OPERATIONS
    )


# ── Simulador: ejecución de extremo a extremo ────────────────────────────────


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


async def test_sim_favorite_set_and_remove_ack_only():
    sim = make_sim()
    subject_id = sim._nodes[1].node_id
    result = await sim.execute_admin(op(sim, "favorite.set", {"subject_node_id": subject_id}))
    assert result["verify"] == "unavailable"  # nunca "confirmed": no hay lectura posible
    assert result["ack"]["ack"] is True
    assert sim._nodes[1].node_num in sim._nodes[0].favorites

    await sim.execute_admin(op(sim, "favorite.remove", {"subject_node_id": subject_id}))
    assert sim._nodes[1].node_num not in sim._nodes[0].favorites


async def test_sim_ignored_set_and_remove():
    sim = make_sim()
    subject_id = sim._nodes[1].node_id
    await sim.execute_admin(op(sim, "ignored.set", {"subject_node_id": subject_id}))
    assert sim._nodes[1].node_num in sim._nodes[0].ignored_nodes
    await sim.execute_admin(op(sim, "ignored.remove", {"subject_node_id": subject_id}))
    assert sim._nodes[1].node_num not in sim._nodes[0].ignored_nodes


async def test_sim_contact_add():
    sim = make_sim()
    subject_id = sim._nodes[1].node_id
    result = await sim.execute_admin(op(sim, "contact.add", {"subject_node_id": subject_id}))
    assert result["verify"] == "unavailable"
    assert sim._nodes[1].node_num in sim._nodes[0].known_contacts
