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
    "neighbors.seen": validator("neighbors_seen.schema.json"),
    "traceroute.completed": validator("traceroute_completed.schema.json"),
    "waypoint.shared": validator("waypoint_shared.schema.json"),
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
    assert payload["rssi"] == -82


def test_position_and_telemetry_carry_radio_metadata():
    """Actividad 2.0 (registro por paquete): rssi/snr deben llegar también en
    posición y telemetría, no solo en node.seen/mensajes (antes faltaban)."""
    position = {
        **BASE_PACKET,
        "decoded": {"portnum": "POSITION_APP", "position": {"latitude": 1, "longitude": 1}},
    }
    _, pos_payload = decode_packet(position)
    assert pos_payload["snr"] == 6.25
    assert pos_payload["rssi"] == -82

    telemetry = {
        **BASE_PACKET,
        "channel": 2,
        "decoded": {
            "portnum": "TELEMETRY_APP",
            "telemetry": {"deviceMetrics": {"batteryLevel": 80}},
        },
    }
    _, tel_payload = decode_packet(telemetry)
    assert tel_payload["snr"] == 6.25
    assert tel_payload["rssi"] == -82
    assert tel_payload["channel_index"] == 2


def test_neighborinfo_packet():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "NEIGHBORINFO_APP",
            "neighborinfo": {
                "neighbors": [
                    {"nodeId": 0xA4E1F2B1, "snr": -8.0},
                    {"nodeId": 0xA4E1F2B2, "snr": -11.5},
                ]
            },
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "neighbors.seen"
    assert payload["node_id"] == "!a4e1f2b0"
    assert payload["neighbors"] == [
        {"neighbor_id": "!a4e1f2b1", "snr": -8.0},
        {"neighbor_id": "!a4e1f2b2", "snr": -11.5},
    ]


def test_neighborinfo_without_neighbors_is_dropped():
    packet = {
        **BASE_PACKET,
        "decoded": {"portnum": "NEIGHBORINFO_APP", "neighborinfo": {"neighbors": []}},
    }
    assert decode_packet(packet) is None


def test_traceroute_with_resolved_route():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "TRACEROUTE_APP",
            "traceroute": {"route": [0xA4E1F2B1, 0xA4E1F2B2], "snrTowards": [6.0, -2.0]},
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "traceroute.completed"
    assert payload["route"] == ["!a4e1f2b1", "!a4e1f2b2"]


def test_traceroute_without_route_is_dropped():
    """Una solicitud sin resolver (route vacío) no es un hecho narrable todavía."""
    packet = {**BASE_PACKET, "decoded": {"portnum": "TRACEROUTE_APP", "traceroute": {"route": []}}}
    assert decode_packet(packet) is None


def test_waypoint_packet():
    packet = {
        **BASE_PACKET,
        "decoded": {
            "portnum": "WAYPOINT_APP",
            "waypoint": {
                "name": "Refugio Sur",
                "description": "Punto de encuentro",
                "latitudeI": 404168333,
                "longitudeI": -37037900,
            },
        },
    }
    decoded = decode_packet(packet)
    assert_valid(decoded)
    event_type, payload = decoded
    assert event_type == "waypoint.shared"
    assert payload["name"] == "Refugio Sur"
    assert round(payload["latitude"], 4) == 40.4168
    assert round(payload["longitude"], 4) == -3.7038


def test_waypoint_without_coordinates_is_dropped():
    packet = {**BASE_PACKET, "decoded": {"portnum": "WAYPOINT_APP", "waypoint": {"name": "x"}}}
    assert decode_packet(packet) is None


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
