"""Registro de capacidades de administración remota (diseño §3/§7).

Fuente de verdad de qué operaciones existen, sus parámetros y propiedades de
seguridad. M1.1: lecturas (GET). M1.3: primeros SET seguros (reversibles,
verificables por lectura posterior, incapaces de dejar un nodo inaccesible).
Añadir una operación = una entrada aquí + su soporte en el gateway.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

# Fuente única de secciones (M1.4): derivadas del esquema protobuf introspeccionado
from noc.application.admin.config_schema import (
    CONFIG_SECTIONS as _SCHEMA_CONFIG_SECTIONS,
    MODULE_CONFIG_SECTIONS as _SCHEMA_MODULE_CONFIG_SECTIONS,
)

CONFIG_SECTIONS = [s.name for s in _SCHEMA_CONFIG_SECTIONS]
MODULE_CONFIG_SECTIONS = [s.name for s in _SCHEMA_MODULE_CONFIG_SECTIONS]

# Límites del firmware (mesh_pb2.User)
OWNER_SHORT_NAME_MAX = 4
OWNER_LONG_NAME_MAX = 39


@dataclass(slots=True, frozen=True)
class ParamField:
    """Metadatos de un parámetro para render y validación en la UI."""

    name: str
    kind: str  # "string" | "number"
    required: bool = False
    max_length: int | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(slots=True, frozen=True)
class OperationSpec:
    operation_type: str
    description: str
    kind: str  # "get" | "set" | "action"
    allow_bulk: bool
    destructive: bool
    required_role: str  # RBAC futuro; hoy informativo (diseño §8)
    param_choices: dict[str, list[str]] = field(default_factory=dict)
    param_fields: list[ParamField] = field(default_factory=list)

    @property
    def requires_confirmation(self) -> bool:
        # Toda escritura exige confirmación explícita del operador (M1.3)
        return self.kind in ("set", "action")


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
        OperationSpec(
            "owner.set",
            "Cambiar nombre corto y/o largo del nodo (con verificación por lectura)",
            kind="set", allow_bulk=False, destructive=False, required_role="admin",
            param_fields=[
                ParamField("short_name", "string", max_length=OWNER_SHORT_NAME_MAX),
                ParamField("long_name", "string", max_length=OWNER_LONG_NAME_MAX),
            ],
        ),
        OperationSpec(
            "position.set_fixed",
            "Fijar posición del nodo (con verificación por lectura)",
            kind="set", allow_bulk=True, destructive=False, required_role="admin",
            param_fields=[
                ParamField("latitude", "number", required=True, minimum=-90, maximum=90),
                ParamField("longitude", "number", required=True, minimum=-180, maximum=180),
                ParamField("altitude", "number", minimum=-500, maximum=10000),
            ],
        ),
        # Editor genérico (M1.4): un tipo por familia; el `section` va en params.
        # Categoría de riesgo real se determina por la sección concreta (ver
        # config_schema.SECTION_RISK) y por el propio conjunto de campos tocados.
        OperationSpec(
            "config.set",
            "Escribir una sección de configuración del dispositivo (con verificación)",
            kind="set", allow_bulk=True, destructive=False, required_role="admin",
            param_choices={"section": CONFIG_SECTIONS},
        ),
        OperationSpec(
            "module_config.set",
            "Escribir una sección de configuración de módulos (con verificación)",
            kind="set", allow_bulk=True, destructive=False, required_role="admin",
            param_choices={"section": MODULE_CONFIG_SECTIONS},
        ),
    ]
}


def _validate_owner_set(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    short, long_ = params.get("short_name"), params.get("long_name")
    if short is None and long_ is None:
        raise ValueError("owner.set requires short_name and/or long_name")
    if short is not None:
        short = str(short).strip()
        if not 1 <= len(short) <= OWNER_SHORT_NAME_MAX:
            raise ValueError(f"short_name must be 1..{OWNER_SHORT_NAME_MAX} characters")
        out["short_name"] = short
    if long_ is not None:
        long_ = str(long_).strip()
        if not 1 <= len(long_) <= OWNER_LONG_NAME_MAX:
            raise ValueError(f"long_name must be 1..{OWNER_LONG_NAME_MAX} characters")
        out["long_name"] = long_
    return out


def _validate_fixed_position(params: dict[str, Any]) -> dict[str, Any]:
    try:
        lat, lon = float(params["latitude"]), float(params["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("position.set_fixed requires numeric latitude and longitude") from exc
    if not -90 <= lat <= 90:
        raise ValueError("latitude out of range [-90, 90]")
    if not -180 <= lon <= 180:
        raise ValueError("longitude out of range [-180, 180]")
    out: dict[str, Any] = {"latitude": lat, "longitude": lon}
    if params.get("altitude") is not None:
        alt = int(params["altitude"])
        if not -500 <= alt <= 10000:
            raise ValueError("altitude out of range [-500, 10000]")
        out["altitude"] = alt
    return out


def _validate_generic_set(section_choices: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Validador para config.set / module_config.set.

    Espera `{section, values: {field: valor}}` y delega la validación de cada
    par (field, valor) al esquema introspeccionado del protobuf. Así el editor
    no necesita lógica por parámetro (M1.4).
    """
    from noc.application.admin.config_schema import validate_field_value

    def validator(params: dict[str, Any]) -> dict[str, Any]:
        section = params.get("section")
        if section not in section_choices:
            raise ValueError(
                f"Parameter 'section' must be one of {section_choices} (got {section!r})"
            )
        values = params.get("values")
        if not isinstance(values, dict) or not values:
            raise ValueError("'values' must be a non-empty object")
        normalized: dict[str, Any] = {}
        for field_name, value in values.items():
            normalized[field_name] = validate_field_value(section, field_name, value)
        return {"section": section, "values": normalized}

    return validator


_VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "owner.set": _validate_owner_set,
    "position.set_fixed": _validate_fixed_position,
    "config.set": _validate_generic_set(CONFIG_SECTIONS),
    "module_config.set": _validate_generic_set(MODULE_CONFIG_SECTIONS),
}


def validate_operation(operation_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Valida y normaliza los parámetros. Lanza ValueError si no son válidos."""
    spec = OPERATIONS.get(operation_type)
    if spec is None:
        raise ValueError(f"Unknown operation_type: {operation_type}")

    validator = _VALIDATORS.get(operation_type)
    if validator is not None:
        # Los validadores dedicados llevan su propio contrato (owner.set,
        # position.set_fixed, config.set, module_config.set); no imponemos aquí
        # una lista blanca de parámetros porque los editores generic usan
        # `values` dict libre validado internamente.
        if operation_type in ("owner.set", "position.set_fixed"):
            allowed = {f.name for f in spec.param_fields}
            unknown = set(params) - allowed
            if unknown:
                raise ValueError(f"Unknown parameters for {operation_type}: {sorted(unknown)}")
        return validator(params)

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
