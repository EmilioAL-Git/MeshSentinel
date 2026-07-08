"""Registro de capacidades de administración remota (diseño §3/§7).

Fuente de verdad de qué operaciones existen, sus parámetros y propiedades de
seguridad. M1.1: exclusivamente lecturas (GET). Añadir una operación = una
entrada aquí + su soporte en el gateway.
"""

from dataclasses import dataclass, field
from typing import Any

CONFIG_SECTIONS = [
    "device", "position", "power", "network", "display", "lora", "bluetooth", "security",
]
MODULE_CONFIG_SECTIONS = [
    "mqtt", "serial", "external_notification", "store_forward", "range_test", "telemetry",
    "canned_message", "audio", "remote_hardware", "neighbor_info", "ambient_lighting",
    "detection_sensor", "paxcounter",
]


@dataclass(slots=True, frozen=True)
class OperationSpec:
    operation_type: str
    description: str
    kind: str  # "get" | "set" | "action"
    allow_bulk: bool
    destructive: bool
    required_role: str  # RBAC futuro; hoy informativo (diseño §8)
    param_choices: dict[str, list[str]] = field(default_factory=dict)


OPERATIONS: dict[str, OperationSpec] = {
    spec.operation_type: spec
    for spec in [
        OperationSpec(
            "metadata.get",
            "Metadatos del dispositivo (firmware, hardware, capacidades)",
            kind="get", allow_bulk=True, destructive=False, required_role="operator",
        ),
        OperationSpec(
            "nodeinfo.get",
            "Identidad del nodo (owner: nombres, licencia)",
            kind="get", allow_bulk=True, destructive=False, required_role="operator",
        ),
        OperationSpec(
            "config.get",
            "Sección de configuración del dispositivo",
            kind="get", allow_bulk=True, destructive=False, required_role="operator",
            param_choices={"section": CONFIG_SECTIONS},
        ),
        OperationSpec(
            "module_config.get",
            "Sección de configuración de módulos",
            kind="get", allow_bulk=True, destructive=False, required_role="operator",
            param_choices={"section": MODULE_CONFIG_SECTIONS},
        ),
    ]
}


def validate_operation(operation_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Valida y normaliza los parámetros. Lanza ValueError si no son válidos."""
    spec = OPERATIONS.get(operation_type)
    if spec is None:
        raise ValueError(f"Unknown operation_type: {operation_type}")
    normalized: dict[str, Any] = {}
    for name, choices in spec.param_choices.items():
        value = params.get(name)
        if value not in choices:
            raise ValueError(f"Parameter '{name}' must be one of {choices} (got {value!r})")
        normalized[name] = value
    unknown = set(params) - set(spec.param_choices)
    if unknown:
        raise ValueError(f"Unknown parameters for {operation_type}: {sorted(unknown)}")
    return normalized
