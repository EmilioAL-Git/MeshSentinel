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


def _node_id_from_num(num: Any) -> str | None:
    """node_num (int, como en NeighborInfo/RouteDiscovery) -> node_id canónico."""
    if not isinstance(num, int) or num < 0:
        return None
    return f"!{num:08x}"


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
    # `fromId` lo resuelve la librería contra su NodeDB en memoria y llega
    # None con frecuencia en mallas reales (nodo aún no cacheado, carrera
    # tras reconectar) — visto en producción vía TCP: paquetes válidos
    # descartados en bloque. `from` (node_num) viene SIEMPRE en el
    # MeshPacket, así que es la fuente canónica; fromId queda solo como
    # atajo si ya viene resuelto.
    node_id = _node_id(packet.get("fromId")) or _node_id_from_num(packet.get("from"))
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
        if payload is None:
            return None
        meta = _radio_metadata(packet)
        payload["snr"] = meta["snr"]
        payload["rssi"] = meta["rssi"]
        return ("position.updated", payload)

    if portnum == "TELEMETRY_APP":
        telemetry = decoded.get("telemetry")
        if not isinstance(telemetry, dict):
            return None
        payload = _telemetry_payload(node_id, telemetry)
        if payload is None:
            return None
        meta = _radio_metadata(packet)
        payload["snr"] = meta["snr"]
        payload["rssi"] = meta["rssi"]
        payload["channel_index"] = packet.get("channel", 0)
        return ("telemetry.received", payload)

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
                "rssi": meta["rssi"],
                "hops_away": meta["hops_away"],
                "packet_id": packet.get("id"),
                "hop_limit": packet.get("hopLimit"),
                "hop_start": packet.get("hopStart"),
            },
        )

    if portnum == "NEIGHBORINFO_APP":
        info = decoded.get("neighborinfo")
        if not isinstance(info, dict):
            return None
        neighbors = []
        for entry in info.get("neighbors") or []:
            if not isinstance(entry, dict):
                continue
            neighbor_id = _node_id_from_num(entry.get("nodeId"))
            if neighbor_id is None:
                continue
            neighbors.append({"neighbor_id": neighbor_id, "snr": entry.get("snr")})
        if not neighbors:
            return None
        meta = _radio_metadata(packet)
        return (
            "neighbors.seen",
            {"node_id": node_id, "neighbors": neighbors, "snr": meta["snr"], "rssi": meta["rssi"]},
        )

    if portnum == "TRACEROUTE_APP":
        trace = decoded.get("traceroute")
        if not isinstance(trace, dict):
            return None
        # `route` lista SOLO los saltos intermedios: un traceroute directo
        # (emisor -> destino en un salto, el caso más común en pruebas de
        # cerca) llega con route vacío y snr_towards con una entrada —
        # verificado en producción. Antes se descartaba como "sin resolver"
        # y los traceroutes directos eran invisibles en el Registro.
        route = [_node_id_from_num(n) for n in (trace.get("route") or [])]
        route_back = [_node_id_from_num(n) for n in (trace.get("routeBack") or [])]
        if any(r is None for r in route) or any(r is None for r in route_back):
            return None
        meta = _radio_metadata(packet)
        # Destinatario del paquete: junto con `node_id` (emisor) permite al
        # backend reconstruir la traza completa (quién la lanzó y hacia quién)
        # a partir del propio paquete, sin depender de que sea la pasarela
        # quien la haya iniciado. 0xffffffff = difusión, no es un nodo.
        to_num = packet.get("to")
        to_node_id = None if to_num == 0xFFFFFFFF else _node_id_from_num(to_num)
        return (
            "traceroute.completed",
            {
                "node_id": node_id,
                "to_node_id": to_node_id,
                # requestId != 0 => RESPUESTA a un traceroute; 0 => la petición
                "is_reply": bool(decoded.get("requestId")),
                "route": route,
                "snr_towards": _snr_db(trace.get("snrTowards")),
                "route_back": route_back,
                "snr_back": _snr_db(trace.get("snrBack")),
                "snr": meta["snr"],
                "rssi": meta["rssi"],
            },
        )

    if portnum == "WAYPOINT_APP":
        waypoint = decoded.get("waypoint")
        if not isinstance(waypoint, dict):
            return None
        lat, lon = waypoint.get("latitudeI"), waypoint.get("longitudeI")
        if lat is None or lon is None:
            return None
        meta = _radio_metadata(packet)
        return (
            "waypoint.shared",
            {
                "node_id": node_id,
                "name": _clip(waypoint.get("name"), 64),
                "description": _clip(waypoint.get("description"), 128),
                "latitude": lat / 1e7,
                "longitude": lon / 1e7,
                "snr": meta["snr"],
                "rssi": meta["rssi"],
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


_UNKNOWN_SNR_RAW = -128  # el firmware marca "sin SNR" así (valores en cuartos de dB)


def _snr_db(raw_list: Any) -> list[float | None]:
    out: list[float | None] = []
    for raw in raw_list or []:
        out.append(None if raw == _UNKNOWN_SNR_RAW else round(raw / 4, 2))
    return out


def traceroute_result(packet: dict[str, Any]) -> dict[str, Any]:
    """Respuesta a un traceroute ACTIVO -> resultado de la operación admin.

    La librería entrega el callback `onResponse` con la respuesta
    TRACEROUTE_APP (ya parseada en `decoded.traceroute`) o con un
    ROUTING_APP si el firmware rechazó/no pudo entregar. `route` lista solo
    los saltos INTERMEDIOS (vacío = alcance directo). Que no haya ruta NO es
    un fallo de la operación: es el resultado ("reached": false)."""
    decoded = packet.get("decoded") or {}
    trace = decoded.get("traceroute")
    if decoded.get("portnum") == "TRACEROUTE_APP" and isinstance(trace, dict):
        route = [_node_id_from_num(n) for n in (trace.get("route") or [])]
        route_back = [_node_id_from_num(n) for n in (trace.get("routeBack") or [])]
        return {
            "reached": True,
            "route": route,
            "snr_towards": _snr_db(trace.get("snrTowards")),
            "route_back": route_back,
            "snr_back": _snr_db(trace.get("snrBack")),
        }
    routing = decoded.get("routing") or {}
    return {"reached": False, "error_reason": routing.get("errorReason") or "UNKNOWN"}
