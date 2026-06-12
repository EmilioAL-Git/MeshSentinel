"""Valida que el simulador emite eventos conformes al contrato shared/events/v1.

Doble propósito (ADR 0006/0007): comprueba que los JSON Schema son válidos y
que la pasarela simulada se mantiene fiel al contrato.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.config import Settings
from gateway.events import make_envelope
from gateway.transports.simulated import SimulatedTransport

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "shared" / "events" / "v1"

PAYLOAD_SCHEMAS = {
    "gateway.status": "gateway_status.schema.json",
    "node.seen": "node_seen.schema.json",
    "position.updated": "position_updated.schema.json",
    "telemetry.received": "telemetry_received.schema.json",
    "message.received": "message_received.schema.json",
}


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


@pytest.fixture(scope="module")
def envelope_validator() -> Draft202012Validator:
    schema = load_schema("envelope.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def payload_validators() -> dict[str, Draft202012Validator]:
    validators = {}
    for event_type, filename in PAYLOAD_SCHEMAS.items():
        schema = load_schema(filename)
        Draft202012Validator.check_schema(schema)
        validators[event_type] = Draft202012Validator(schema, format_checker=FormatChecker())
    return validators


def test_command_schema_is_valid() -> None:
    Draft202012Validator.check_schema(load_schema("command.schema.json"))


async def test_simulator_events_conform_to_contract(envelope_validator, payload_validators) -> None:
    captured: list[dict] = []

    async def emit(event_type: str, payload: dict) -> None:
        captured.append(make_envelope(event_type, "gw-test", payload))

    settings = Settings(transport="simulated", sim_node_count=8, sim_seed=7)
    sim = SimulatedTransport(emit, settings)

    # Anuncio inicial + varios ticks de toda la malla
    for node in sim._nodes:
        await sim._announce(node)
    for _ in range(20):
        for node in sim._nodes:
            await sim._tick(node, elapsed=15)
    await sim.close()

    assert len(captured) > 8, "el simulador debe emitir anuncios y telemetría"
    seen_types = {e["event_type"] for e in captured}
    assert {"node.seen", "telemetry.received", "position.updated", "gateway.status"} <= seen_types

    for event in captured:
        envelope_validator.validate(event)
        payload_validators[event["event_type"]].validate(event["payload"])
