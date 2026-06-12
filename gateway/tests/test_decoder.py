"""El decodificador USB debe producir payloads conformes al contrato v1,
partiendo de dicts con el formato real de la librería oficial."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.decoder.meshtastic import decode_nodedb_entry, decode_packet

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "shared" / "events" / "v1"


def validator(filename: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS_DIR / filename).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


SCHEMA_BY_TYPE = {
    "node.seen": validator("node_seen.schema.json"),
    "position.updated": validator("position_updated.schema.json"),
    "telemetry.received": validator("telemetry_received.schema.json"),
    "message.received": validator("message_received.schema.json"),
}


def assert_valid(decoded) -> None:
    assert decoded is not None
    event_type, payload = decoded
    SCHEMA_BY_TYPE[event_type].validate(payload)


BASE_PACKET = {
    "from": 0xA4E1F2B0,
    "fromId": "!a4e1f2b0",
    "toId": "^all",
    "id": 123456,
    "rxSnr": 6.25,
    "rxRssi": -82,
    "hopStart": 3,
    "hopLimit": 2,
    "viaMqtt": False,
}


def test_nodeinfo_packet():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "NODEINFO_APP",
            "user": {
                "id": "!a4e1f2b0",
                "longName": "Nodo de pruebas con un nombre exageradamente largo que hay que recortar porque sí",
                "shortName": "PRUEBAS!!",
                "hwModel": "TBEAM",
                "role": "ROUTER",
                "publicKey": "Zm9vYmFy",
            },
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "node.seen"
    assert payload["hops_away"] == 1
    assert len(payload["short_name"]) <= 8
    assert len(payload["long_name"]) <= 64


def test_position_packet():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "POSITION_APP",
            "position": {
                "latitude": 40.4168333,
                "longitude": -3.70379,
                "altitude": 657,
                "time": 1765531200,
                "satsInView": 7,
                "precisionBits": 32,
            },
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "position.updated"
    assert payload["position_time"].startswith("2025-12-12")


def test_position_without_coordinates_is_dropped():
    packet = {**BASE_PACKET, "decoded": {"portnum": "POSITION_APP", "position": {"time": 1}}}
    assert decode_packet(packet) is None


def test_device_telemetry_packet():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "TELEMETRY_APP",
            "telemetry": {
                "time": 1765531200,
                "deviceMetrics": {
                    "batteryLevel": 113,  # la librería puede reportar >101 con USB
                    "voltage": 4.05,
                    "channelUtilization": 11.5,
                    "airUtilTx": 2.8,
                    "uptimeSeconds": 86400,
                },
            },
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "telemetry.received"
    assert payload["kind"] == "device"
    assert payload["battery_level"] == 101  # recortado al máximo del contrato


def test_environment_telemetry_packet():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "TELEMETRY_APP",
            "telemetry": {
                "environmentMetrics": {"temperature": 21.4, "relativeHumidity": 48.0, "barometricPressure": 1013.2}
            },
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    assert decoded[1]["kind"] == "environment"
    assert decoded[1]["temperature_c"] == 21.4


def test_text_message_packet():
    packet = {
        **BASE_PACKET,
        "toId": "!deadbeef",
        "channel": 1,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hola malla"},
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "message.received"
    assert payload["to_node_id"] == "!deadbeef"
    assert payload["channel_index"] == 1


@pytest.mark.parametrize(
    "packet",
    [
        {"fromId": None, "decoded": {"portnum": "POSITION_APP", "position": {"latitude": 1, "longitude": 1}}},
        {**BASE_PACKET, "decoded": {"portnum": "ADMIN_APP", "admin": {}}},
        {**BASE_PACKET},  # paquete cifrado sin 'decoded'
        {"fromId": "^all", "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "x"}},
    ],
)
def test_unusable_packets_return_none(packet):
    assert decode_packet(packet) is None


def test_nodedb_entry():
    entry = {
        "num": 0xDEADBEEF,
        "user": {"id": "!deadbeef", "longName": "Repetidor sierra", "shortName": "SIER", "hwModel": "RAK4631"},
        "snr": 9.5,
        "hopsAway": 2,
        "lastHeard": 1765444800,
        "deviceMetrics": {"batteryLevel": 88},
    }
    decoded = decode_nodedb_entry("!DEADBEEF", entry)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "node.seen"
    assert payload["node_id"] == "!deadbeef"  # normalizado a minúsculas
    assert payload["last_heard"] is not None
    assert payload["hops_away"] == 2


def test_nodedb_entry_invalid_id():
    assert decode_nodedb_entry("4275878532", {"num": 1}) is None
