"""Cuerpos de las solicitudes por radio sin admin (request.send).

Módulo acoplado a la librería oficial (ADR 0009). Cada kind es un paquete
normal de su puerto con want_response=True; el firmware destino contesta con
su dato actual.
"""

from typing import Any

from google.protobuf import json_format
from meshtastic.protobuf import mesh_pb2, paxcount_pb2, portnums_pb2, telemetry_pb2

_TELEMETRY_VARIANTS = {
    "device_metrics": "device_metrics",
    "environment_metrics": "environment_metrics",
    "air_quality_metrics": "air_quality_metrics",
    "power_metrics": "power_metrics",
    "local_stats": "local_stats",
    "health_metrics": "health_metrics",
    "host_metrics": "host_metrics",
}


def _my_user(iface: Any) -> mesh_pb2.User:
    """Identidad del nodo local: la app oficial la envía en la solicitud para
    que el destino también conozca al solicitante."""
    user = mesh_pb2.User()
    try:
        raw = iface.getMyUser() or {}
        json_format.ParseDict(raw, user, ignore_unknown_fields=True)
    except Exception:
        pass
    return user


def build_request(kind: str, iface: Any) -> tuple[Any, int]:
    """(mensaje protobuf, portnum) de la solicitud `kind`."""
    if kind == "user_info":
        return _my_user(iface), portnums_pb2.PortNum.NODEINFO_APP
    if kind == "position":
        return mesh_pb2.Position(), portnums_pb2.PortNum.POSITION_APP
    if kind == "pax_metrics":
        return paxcount_pb2.Paxcount(), portnums_pb2.PortNum.PAXCOUNTER_APP
    variant = _TELEMETRY_VARIANTS.get(kind)
    if variant is None:
        raise ValueError(f"Unsupported request kind: {kind}")
    msg = telemetry_pb2.Telemetry()
    getattr(msg, variant).SetInParent()
    return msg, portnums_pb2.PortNum.TELEMETRY_APP
