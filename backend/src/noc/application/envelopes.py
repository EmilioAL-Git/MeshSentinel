"""Construcción de envelopes v1 (`shared/events`, ADR 0006) del lado backend.

Único punto de construcción: antes de la consolidación pre-M6 había tres
implementaciones manuales casi idénticas (AdminOperationService, GatewayService,
el broadcaster de alertas de main.py) que podían divergir con el tiempo. No
sustituye a `gateway/events.py::make_envelope` — es el equivalente del otro
lado del proceso (ADR 0001: gateway y backend son paquetes desacoplados, sin
imports cruzados, cada uno con su propio helper).
"""

import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1

# Origen de eventos internos del backend (alertas, actividad) que no vienen de
# ningún proceso gateway real. Nunca debe coincidir con un gateway_id real
# (que siempre sigue el patrón "gw-*") — evita ambigüedad de cara a
# Multi-Gateway, donde "gateway_id" empezará a tener significado de rutado.
SYSTEM_SOURCE = "system"


def make_event_envelope(
    event_type: str, payload: dict[str, Any], gateway_id: str = SYSTEM_SOURCE
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def make_command_envelope(
    command_type: str,
    payload: dict[str, Any],
    issued_by: str = "admin",
    target_node_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command_type": command_type,
        "command_id": str(uuid.uuid4()),
        "issued_by": issued_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_node_id": target_node_id,
        "payload": payload,
    }
