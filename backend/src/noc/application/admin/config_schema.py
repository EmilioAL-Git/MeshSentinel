"""Introspección del esquema de configuración a partir de los protobufs de la
librería oficial (M1.4). Fuente única de metadatos para el editor de
configuración: sin lógica por parámetro en backend ni frontend.

El módulo se importa desde el backend Y desde el gateway. Ambos lo usan sin
tocar la librería fuera de gateway/decoder|transports (ADR 0002).
"""

from dataclasses import dataclass, field
from typing import Any

from google.protobuf.descriptor import FieldDescriptor as FD
from meshtastic.protobuf import config_pb2, module_config_pb2

# Clasificación de riesgo por sección (referencia del usuario M1.4)
SAFE = "SAFE"
WARNING = "WARNING"
DANGEROUS = "DANGEROUS"

SECTION_RISK: dict[str, str] = {
    # Config
    "device": WARNING,       # incluye role, rebroadcast_mode
    "position": SAFE,
    "power": WARNING,
    "network": WARNING,      # WiFi/ethernet
    "display": SAFE,
    "lora": WARNING,         # región, potencia, hop_limit
    "bluetooth": SAFE,
    "security": DANGEROUS,   # claves, admin_key
    "device_ui": SAFE,
    # Module config
    "mqtt": SAFE,
    "serial": SAFE,
    "external_notification": SAFE,
    "store_forward": SAFE,
    "range_test": SAFE,
    "telemetry": SAFE,
    "canned_message": SAFE,
    "audio": SAFE,
    "remote_hardware": SAFE,
    "neighbor_info": SAFE,
    "ambient_lighting": SAFE,
    "detection_sensor": SAFE,
    "paxcounter": SAFE,
    "statusmessage": SAFE,
    "traffic_management": SAFE,
    "tak": SAFE,
}

# Descripciones legibles (las que no encajan con el nombre de la sección)
SECTION_DESCRIPTION: dict[str, str] = {
    "device": "Identidad del hardware, botón, buzzer, comportamiento general",
    "position": "GPS, difusión de posición",
    "power": "Batería, ahorro de energía, sueño",
    "network": "WiFi, Ethernet, NTP",
    "display": "Pantalla, brillo, temporizadores",
    "lora": "Región, banda, potencia, hop limit, preset",
    "bluetooth": "Emparejamiento y PIN",
    "security": "Claves PKC y admin (peligroso)",
    "device_ui": "Parámetros de UI del dispositivo",
    "mqtt": "Puente MQTT",
    "telemetry": "Cadencia de telemetría device/environment/power",
    "position_module": "Posición (módulo)",
    "canned_message": "Mensajes enlatados",
    "external_notification": "Notificaciones externas (GPIO)",
    "store_forward": "Store & Forward",
    "range_test": "Prueba de alcance",
    "serial": "Puerto serie del módulo",
    "neighbor_info": "Compartir información de vecinos",
    "ambient_lighting": "Iluminación ambiente",
    "detection_sensor": "Sensor de detección (GPIO)",
    "paxcounter": "Contador PAX (WiFi/BT)",
    "audio": "Audio (codec2)",
    "remote_hardware": "Acceso remoto a GPIO",
    "statusmessage": "Mensajes de estado",
    "traffic_management": "Gestión de tráfico",
    "tak": "Team Awareness Kit",
}

# Grupos para la UI (agrupación visual, no lógica)
UI_GROUPS: dict[str, list[str]] = {
    "General": ["owner"],
    "Radio": ["lora", "bluetooth", "network"],
    "Dispositivo": ["device", "power", "display", "device_ui"],
    "Seguridad": ["security"],
    "Ubicación": ["position"],
    "Módulos": [
        "mqtt", "telemetry", "canned_message", "external_notification", "store_forward",
        "range_test", "serial", "neighbor_info", "ambient_lighting", "detection_sensor",
        "paxcounter", "audio", "remote_hardware", "statusmessage", "traffic_management", "tak",
    ],
}


# ── Introspección de un campo protobuf ─────────────────────────────────────────


@dataclass(slots=True)
class FieldMeta:
    name: str
    kind: str  # bool | int | float | str | enum | message | bytes | repeated
    enum_values: list[str] = field(default_factory=list)
    repeated: bool = False
    submessage: str | None = None  # nombre del tipo si kind=message
    # Rangos no están en el proto: se dejan None y la UI valida por tipo
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""


@dataclass(slots=True)
class SectionMeta:
    name: str
    display_name: str
    kind: str  # "config" | "module_config" | "owner"
    risk: str  # SAFE | WARNING | DANGEROUS
    description: str
    fields: list[FieldMeta] = field(default_factory=list)


_INT_KINDS = {
    FD.TYPE_UINT32: "int", FD.TYPE_INT32: "int", FD.TYPE_UINT64: "int", FD.TYPE_INT64: "int",
    FD.TYPE_FIXED32: "int", FD.TYPE_FIXED64: "int", FD.TYPE_SFIXED32: "int", FD.TYPE_SFIXED64: "int",
    FD.TYPE_SINT32: "int", FD.TYPE_SINT64: "int",
}
_FLOAT_KINDS = {FD.TYPE_FLOAT: "float", FD.TYPE_DOUBLE: "float"}


def _field_kind(descriptor: Any) -> str:
    t = descriptor.type
    if t == FD.TYPE_BOOL:
        return "bool"
    if t == FD.TYPE_STRING:
        return "str"
    if t == FD.TYPE_BYTES:
        return "bytes"
    if t == FD.TYPE_ENUM:
        return "enum"
    if t == FD.TYPE_MESSAGE:
        return "message"
    return _INT_KINDS.get(t) or _FLOAT_KINDS.get(t) or "unknown"


def _repeated(descriptor: Any) -> bool:
    # `label` fue eliminado en versiones recientes de protobuf; usamos label_ del
    # descriptor si existe, si no `LABEL_REPEATED` numérico (3)
    label = getattr(descriptor, "label", None)
    if label is not None:
        return label == 3  # LABEL_REPEATED
    return False


def _describe_field(descriptor: Any) -> FieldMeta:
    kind = _field_kind(descriptor)
    meta = FieldMeta(name=descriptor.name, kind=kind, repeated=_repeated(descriptor))
    if kind == "enum" and descriptor.enum_type is not None:
        meta.enum_values = [v.name for v in descriptor.enum_type.values]
    elif kind == "message" and descriptor.message_type is not None:
        meta.submessage = descriptor.message_type.name
    return meta


def _describe_message(msg_desc: Any) -> list[FieldMeta]:
    return [_describe_field(f) for f in msg_desc.fields]


def _section_name(oneof_field: Any) -> str:
    return oneof_field.name


def _display_name(name: str) -> str:
    return name.replace("_", " ").title()


# ── Esquema completo (calculado una vez a la carga del módulo) ─────────────────


def _build_config_sections() -> list[SectionMeta]:
    sections: list[SectionMeta] = []
    for oneof_f in config_pb2.Config.DESCRIPTOR.fields:
        if not oneof_f.message_type:
            continue
        fields = _describe_message(oneof_f.message_type)
        if not fields:  # sessionkey está vacío
            continue
        name = _section_name(oneof_f)
        sections.append(
            SectionMeta(
                name=name,
                display_name=_display_name(name),
                kind="config",
                risk=SECTION_RISK.get(name, SAFE),
                description=SECTION_DESCRIPTION.get(name, ""),
                fields=fields,
            )
        )
    return sections


def _build_module_sections() -> list[SectionMeta]:
    sections: list[SectionMeta] = []
    for oneof_f in module_config_pb2.ModuleConfig.DESCRIPTOR.fields:
        if not oneof_f.message_type:
            continue
        fields = _describe_message(oneof_f.message_type)
        if not fields:
            continue
        name = _section_name(oneof_f)
        sections.append(
            SectionMeta(
                name=name,
                display_name=_display_name(name),
                kind="module_config",
                risk=SECTION_RISK.get(name, SAFE),
                description=SECTION_DESCRIPTION.get(name, ""),
                fields=fields,
            )
        )
    return sections


def _build_owner_section() -> SectionMeta:
    return SectionMeta(
        name="owner",
        display_name="General",
        kind="owner",
        risk=SAFE,
        description="Identidad del nodo (nombre corto y largo)",
        fields=[
            FieldMeta(name="short_name", kind="str", description="Máx. 4 caracteres"),
            FieldMeta(name="long_name", kind="str", description="Máx. 39 caracteres"),
        ],
    )


CONFIG_SECTIONS: list[SectionMeta] = _build_config_sections()
MODULE_CONFIG_SECTIONS: list[SectionMeta] = _build_module_sections()
OWNER_SECTION: SectionMeta = _build_owner_section()

ALL_SECTIONS: dict[str, SectionMeta] = {
    OWNER_SECTION.name: OWNER_SECTION,
    **{s.name: s for s in CONFIG_SECTIONS},
    **{s.name: s for s in MODULE_CONFIG_SECTIONS},
}


def section_field_names(section: str) -> set[str]:
    meta = ALL_SECTIONS.get(section)
    return {f.name for f in meta.fields} if meta else set()


def validate_field_value(section: str, field_name: str, value: Any) -> Any:
    """Valida y normaliza un valor contra el esquema. Lanza ValueError.

    Permite que la interfaz siga siendo genérica: la validación exhaustiva
    (rangos por campo del firmware) ocurre en el nodo — aquí solo se aplican
    las restricciones deducibles del protobuf.
    """
    meta = ALL_SECTIONS.get(section)
    if meta is None:
        raise ValueError(f"Unknown section: {section}")
    fmeta = next((f for f in meta.fields if f.name == field_name), None)
    if fmeta is None:
        raise ValueError(f"Unknown field '{field_name}' in section '{section}'")
    if fmeta.repeated or fmeta.kind == "message":
        # No editable desde el editor genérico M1.4
        raise ValueError(f"Field '{field_name}' is not editable from the generic editor")
    if fmeta.kind == "bool":
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "on"):
                return True
            if v in ("false", "0", "no", "off", ""):
                return False
            raise ValueError(f"invalid boolean for '{field_name}': {value!r}")
        return bool(value)
    if fmeta.kind == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"invalid integer for '{field_name}': {value!r}") from None
    if fmeta.kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"invalid float for '{field_name}': {value!r}") from None
    if fmeta.kind == "enum":
        v = str(value)
        if v not in fmeta.enum_values:
            raise ValueError(
                f"invalid enum '{v}' for '{field_name}'; allowed: {fmeta.enum_values}"
            )
        return v
    if fmeta.kind == "str":
        return str(value)
    if fmeta.kind == "bytes":
        # base64 esperado desde la API; no lo tocamos aquí
        return value
    raise ValueError(f"unsupported kind '{fmeta.kind}' for '{field_name}'")


def to_dict(section: SectionMeta) -> dict[str, Any]:
    return {
        "name": section.name,
        "display_name": section.display_name,
        "kind": section.kind,
        "risk": section.risk,
        "description": section.description,
        "fields": [
            {
                "name": f.name,
                "kind": f.kind,
                "enum_values": f.enum_values,
                "repeated": f.repeated,
                "submessage": f.submessage,
                "editable": not f.repeated and f.kind != "message",
                "description": f.description,
            }
            for f in section.fields
        ],
    }
