import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.config import Settings
from gateway.command_queue.consumer import CommandConsumer
from gateway.decoder.admin import (
    CONFIG_SECTION_TO_ENUM,
    MODULE_SECTION_TO_ENUM,
    build_admin_request,
)
from gateway.events import make_envelope
from gateway.transports.base import Transport
from gateway.transports.simulated import SimulatedTransport

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "shared" / "events" / "v1"


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((SCHEMAS_DIR / name).read_text()), format_checker=FormatChecker()
    )


# ── build_admin_request ──────────────────────────────────────────────────────


def test_build_all_config_sections():
    for section in CONFIG_SECTION_TO_ENUM:
        msg, key = build_admin_request("config.get", {"section": section})
        assert key == "getConfigResponse"
        assert msg.HasField("get_config_request") or msg.get_config_request == 0


def test_build_all_module_sections():
    for section in MODULE_SECTION_TO_ENUM:
        _, key = build_admin_request("module_config.get", {"section": section})
        assert key == "getModuleConfigResponse"


def test_build_metadata_and_nodeinfo():
    msg, key = build_admin_request("metadata.get", {})
    assert key == "getDeviceMetadataResponse" and msg.get_device_metadata_request
    msg, key = build_admin_request("nodeinfo.get", {})
    assert key == "getOwnerResponse" and msg.get_owner_request


def test_build_rejects_unknown_operation():
    with pytest.raises(ValueError):
        build_admin_request("config.set", {})


# ── Transporte simulado ──────────────────────────────────────────────────────


class StubRng:
    """Determinista y rápido: sin latencia y sin pérdida de paquetes."""

    def uniform(self, a: float, b: float) -> float:  # noqa: ARG002
        return 0.0

    def random(self) -> float:
        return 0.99


def make_sim() -> SimulatedTransport:
    async def emit(event_type, payload):  # noqa: ARG001
        pass

    sim = SimulatedTransport(emit, Settings(_env_file=None, transport="simulated", sim_node_count=4, sim_seed=7))
    for node in sim._nodes:
        node.rng = StubRng()
    return sim


def op(sim: SimulatedTransport, op_type: str, params: dict | None = None) -> dict:
    return {
        "operation_id": 1,
        "operation_type": op_type,
        "params": params or {},
        "timeout_seconds": 5,
        "target_node_id": sim._nodes[0].node_id,
    }


async def test_simulated_admin_all_operations():
    sim = make_sim()
    assert "firmwareVersion" in await sim.execute_admin(op(sim, "metadata.get"))
    assert (await sim.execute_admin(op(sim, "nodeinfo.get")))["id"] == sim._nodes[0].node_id
    assert "lora" in await sim.execute_admin(op(sim, "config.get", {"section": "lora"}))
    assert "mqtt" in await sim.execute_admin(op(sim, "module_config.get", {"section": "mqtt"}))


async def test_simulated_admin_unknown_node_times_out():
    sim = make_sim()
    operation = op(sim, "metadata.get")
    operation["target_node_id"] = "!ffffffff"
    with pytest.raises(TimeoutError):
        await sim.execute_admin(operation)


# ── CommandConsumer: ciclo de vida publicado conforme al contrato ────────────


class FakeTransport(Transport):
    name = "fake"

    def __init__(self, behavior: str) -> None:
        super().__init__(emit=None)  # type: ignore[arg-type]
        self._behavior = behavior

    async def run(self) -> None: ...
    async def close(self) -> None: ...
    async def send_command(self, command): ...

    async def execute_admin(self, operation):
        if self._behavior == "ok":
            return {"firmwareVersion": "2.7.0"}
        if self._behavior == "timeout":
            raise TimeoutError("no response")
        raise RuntimeError("boom")


class FakeManager:
    """Sustituye a TransportManager en el test: solo expone `.transport`."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport


def make_consumer(behavior: str):
    published: list[dict] = []

    async def publish(event_type: str, payload: dict) -> None:
        published.append(make_envelope(event_type, "gw-test", payload))

    manager = FakeManager(FakeTransport(behavior))
    consumer = CommandConsumer("redis://localhost:6399/0", "s", "g", manager, publish)
    return consumer, published


def command() -> dict:
    return {
        "schema_version": 1,
        "command_type": "command.send_admin",
        "command_id": "00000000-0000-0000-0000-000000000000",
        "issued_by": "admin",
        "timestamp": "2026-07-08T00:00:00+00:00",
        "target_node_id": "!a1b2c3d4",
        "payload": {"operation_id": 42, "operation_type": "metadata.get", "params": {}, "timeout_seconds": 5},
    }


@pytest.mark.parametrize(
    ("behavior", "final_state"),
    [("ok", "succeeded"), ("timeout", "timeout"), ("error", "failed")],
)
async def test_consumer_publishes_lifecycle(behavior, final_state):
    consumer, published = make_consumer(behavior)
    await consumer._handle_admin(command())

    envelope_v = validator("envelope.schema.json")
    payload_v = validator("admin_operation_update.schema.json")
    assert [e["payload"]["state"] for e in published] == ["running", final_state]
    for envelope in published:
        envelope_v.validate(envelope)
        payload_v.validate(envelope["payload"])
        assert envelope["payload"]["operation_id"] == 42
    if final_state == "succeeded":
        assert published[-1]["payload"]["result"] == {"firmwareVersion": "2.7.0"}
    else:
        assert published[-1]["payload"]["error"]
