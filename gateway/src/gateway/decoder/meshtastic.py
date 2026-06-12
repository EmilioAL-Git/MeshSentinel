"""Traducción de estructuras de la librería oficial `meshtastic` al contrato
shared/events/v1 (ADR 0009).

Funciones puras sobre los dicts que produce la librería (paquetes decodificados
y entradas de NodeDB): sin I/O, testeables sin hardware. Cualquier cambio de
formato entre versiones de la librería se absorbe aquí.
"""

import re
from datetime import datetime, timezone
from typing import Any

NODE_ID_RE = re.compile(r"^![0-9a-f]{8}$")

DecodedEvent = tuple[str, dict[str, Any]]

_TELEMETRY_KINDS = {
    "deviceMetrics": "device",
    "environmentMetrics": "environment",
    "powerMetrics": "power",
}


def _node_id(raw: Any) -> str | None:
    if isinstance(raw, str) and NODE_ID_RE.match(raw.lower()):
        return raw.lower()
    return None


def _epoch_to_iso(epoch: Any) -> str | None:
    if not isinstance(epoch, (int, float)) or epoch <= 0:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _clip(value: Any, max_len: int) -> str | None:
    return str(value)[:max_len] if value is not None else None


def _user_payload(node_id: str, user: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "short_name": _clip(user.get("shortName"), 8),
        "long_name": _clip(user.get("longName"), 64),
        "hw_model": _clip(user.get("hwModel"), 32),
        "role": user.get("role"),
        "public_key": user.get("publicKey"),
    }


def _position_payload(node_id: str, pos: dict[str, Any]) -> dict[str, Any] | None:
    lat, lon = pos.get("latitude"), pos.get("longitude")
    if lat is None or lon is None:
        return None
    return {
        "node_id": node_id,
        "latitude": lat,
        "longitude": lon,
        "altitude_m": pos.get("altitude"),
        "precision_bits": pos.get("precisionBits"),
        "sats_in_view": pos.get("satsInView"),
        "position_time": _epoch_to_iso(pos.get("time")),
    }


def _telemetry_payload(node_id: str, telemetry: dict[str, Any]) -> dict[str, Any] | None:
    for lib_key, kind in _TELEMETRY_KINDS.items():
        metrics = telemetry.get(lib_key)
        if not isinstance(metrics, dict):
            continue
        battery = metrics.get("batteryLevel")
        return {
            "node_id": node_id,
            "kind": kind,
            "battery_level": min(int(battery), 101) if battery is not None else None,
            "voltage": metrics.get("voltage"),
            "channel_utilization": metrics.get("channelUtilization"),
            "air_util_tx": metrics.get("airUtilTx"),
            "uptime_seconds": metrics.get("uptimeSeconds"),
            "temperature_c": metrics.get("temperature"),
            "relative_humidity": metrics.get("relativeHumidity"),
            "barometric_pressure_hpa": metrics.get("barometricPressure"),
        }
    return None


def _radio_metadata(packet: dict[str, Any]) -> dict[str, Any]:
    hops_away = None
    hop_start, hop_limit = packet.get("hopStart"), packet.get("hopLimit")
    if isinstance(hop_start, int) and isinstance(hop_limit, int) and hop_start >= hop_limit:
        hops_away = hop_start - hop_limit
    return {
        "snr": packet.get("rxSnr"),
        "rssi": packet.get("rxRssi"),
        "hops_away": hops_away,
        "via_mqtt": bool(packet.get("viaMqtt", False)),
    }


def decode_packet(packet: dict[str, Any]) -> DecodedEvent | None:
    """Paquete recibido (topic meshtastic.receive) -> evento v1, o None si no aplica."""
    decoded = packet.get("decoded")
    node_id = _node_id(packet.get("fromId"))
    if not isinstance(decoded, dict) or node_id is None:
        return None

    portnum = decoded.get("portnum")

    if portnum == "NODEINFO_APP":
        user = decoded.get("user")
        if not isinstance(user, dict):
            return None
        payload = _user_payload(node_id, user)
        payload["node_num"] = packet.get("from")
        payload.update(_radio_metadata(packet))
        return ("node.seen", payload)

    if portnum == "POSITION_APP":
        pos = decoded.get("position")
        if not isinstance(pos, dict):
            return None
        payload = _position_payload(node_id, pos)
        return ("position.updated", payload) if payload else None

    if portnum == "TELEMETRY_APP":
        telemetry = decoded.get("telemetry")
        if not isinstance(telemetry, dict):
            return None
        payload = _telemetry_payload(node_id, telemetry)
        return ("telemetry.received", payload) if payload else None

    if portnum == "TEXT_MESSAGE_APP":
        text = decoded.get("text")
        if not isinstance(text, str):
            return None
        meta = _radio_metadata(packet)
        return (
            "message.received",
            {
                "from_node_id": node_id,
                "to_node_id": _node_id(packet.get("toId")),
                "channel_index": packet.get("channel", 0),
                "text": text[:512],
                "snr": meta["snr"],
                "hops_away": meta["hops_away"],
            },
        )

    return None


def decode_nodedb_entry(node_id_raw: str, entry: dict[str, Any]) -> DecodedEvent | None:
    """Entrada de interface.nodes (NodeDB del dispositivo) -> node.seen, o None.

    Solo se emite node.seen: las posiciones del snapshot pueden ser antiguas y
    contaminarían la serie histórica con la hora de recepción actual.
    `last_heard` (opcional en el contrato) preserva la antigüedad real.
    """
    node_id = _node_id(node_id_raw)
    if node_id is None:
        return None
    user = entry.get("user") if isinstance(entry.get("user"), dict) else {}
    payload = _user_payload(node_id, user)
    payload["node_num"] = entry.get("num")
    payload["snr"] = entry.get("snr")
    payload["hops_away"] = entry.get("hopsAway")
    payload["via_mqtt"] = bool(entry.get("viaMqtt", False))
    payload["last_heard"] = _epoch_to_iso(entry.get("lastHeard"))
    return ("node.seen", payload)
