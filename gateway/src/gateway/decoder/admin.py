"""Construcción de peticiones AdminMessage (GET M1.1, SET verificables M1.3,
editor completo M1.4) — módulo acoplado a la librería oficial (ADR 0009).

M1.4: los SET `config.set` y `module_config.set` toman `{section, values}` y
construyen la petición fusionando los cambios con la lectura previa, para que
los campos no tocados NO se reseteen a defaults del firmware.
"""

from dataclasses import dataclass
from typing import Any, Callable

from google.protobuf import json_format
from google.protobuf.descriptor import FieldDescriptor as FD
from meshtastic.protobuf import admin_pb2, config_pb2, module_config_pb2

CONFIG_SECTION_TO_ENUM = {
    "device": "DEVICE_CONFIG",
    "position": "POSITION_CONFIG",
    "power": "POWER_CONFIG",
    "network": "NETWORK_CONFIG",
    "display": "DISPLAY_CONFIG",
    "lora": "LORA_CONFIG",
    "bluetooth": "BLUETOOTH_CONFIG",
    "security": "SECURITY_CONFIG",
    "device_ui": "DEVICEUI_CONFIG",
}

MODULE_SECTION_TO_ENUM = {
    "mqtt": "MQTT_CONFIG",
    "serial": "SERIAL_CONFIG",
    "external_notification": "EXTNOTIF_CONFIG",
    "store_forward": "STOREFORWARD_CONFIG",
    "range_test": "RANGETEST_CONFIG",
    "telemetry": "TELEMETRY_CONFIG",
    "canned_message": "CANNEDMSG_CONFIG",
    "audio": "AUDIO_CONFIG",
    "remote_hardware": "REMOTEHARDWARE_CONFIG",
    "neighbor_info": "NEIGHBORINFO_CONFIG",
    "ambient_lighting": "AMBIENTLIGHTING_CONFIG",
    "detection_sensor": "DETECTIONSENSOR_CONFIG",
    "paxcounter": "PAXCOUNTER_CONFIG",
    "statusmessage": "STATUSMESSAGE_CONFIG",
    "traffic_management": "TRAFFICMANAGEMENT_CONFIG",
    "tak": "TAK_CONFIG",
}


def _snake_to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(word.title() for word in tail)


def _read_field(section_dict: dict[str, Any], field_name: str) -> Any:
    """Los responses vienen camelCased (asDict). Aceptamos ambas variantes."""
    if field_name in section_dict:
        return section_dict[field_name]
    return section_dict.get(_snake_to_camel(field_name))


def build_admin_request(operation_type: str, params: dict[str, Any]) -> tuple[Any, str]:
    """(AdminMessage, clave de respuesta esperada en decoded['admin'])."""
    msg = admin_pb2.AdminMessage()
    if operation_type == "metadata.get":
        msg.get_device_metadata_request = True
        return msg, "getDeviceMetadataResponse"
    if operation_type == "nodeinfo.get":
        msg.get_owner_request = True
        return msg, "getOwnerResponse"
    if operation_type == "config.get":
        enum_name = CONFIG_SECTION_TO_ENUM[params["section"]]
        msg.get_config_request = admin_pb2.AdminMessage.ConfigType.Value(enum_name)
        return msg, "getConfigResponse"
    if operation_type == "module_config.get":
        enum_name = MODULE_SECTION_TO_ENUM[params["section"]]
        msg.get_module_config_request = admin_pb2.AdminMessage.ModuleConfigType.Value(enum_name)
        return msg, "getModuleConfigResponse"
    raise ValueError(f"Unsupported admin operation: {operation_type}")


# ── Operaciones SET (M1.3): mensaje SET + GET de verificación + comparador ───


def build_owner_set(params: dict[str, Any], previous: dict[str, Any] | None = None) -> Any:  # noqa: ARG001
    msg = admin_pb2.AdminMessage()
    if params.get("short_name") is not None:
        msg.set_owner.short_name = params["short_name"]
    if params.get("long_name") is not None:
        msg.set_owner.long_name = params["long_name"]
    return msg


def compare_owner(params: dict[str, Any], read: dict[str, Any]) -> bool:
    if "short_name" in params and read.get("shortName") != params["short_name"]:
        return False
    if "long_name" in params and read.get("longName") != params["long_name"]:
        return False
    return True


def build_fixed_position_set(params: dict[str, Any], previous: dict[str, Any] | None = None) -> Any:  # noqa: ARG001
    msg = admin_pb2.AdminMessage()
    msg.set_fixed_position.latitude_i = int(round(params["latitude"] * 1e7))
    msg.set_fixed_position.longitude_i = int(round(params["longitude"] * 1e7))
    if params.get("altitude") is not None:
        msg.set_fixed_position.altitude = int(params["altitude"])
    return msg


def compare_fixed_position(params: dict[str, Any], read: dict[str, Any]) -> bool:  # noqa: ARG001
    position = read.get("position") if isinstance(read.get("position"), dict) else {}
    return bool(position.get("fixedPosition"))


# ── Operaciones SET genéricas (M1.4) ─────────────────────────────────────────


def _fill_message_from_dict(msg: Any, source: dict[str, Any]) -> None:
    """Rellena `msg` a partir de un dict camelCased de asDict.
    Ignora campos desconocidos para tolerar cambios de firmware.
    """
    try:
        json_format.ParseDict(source, msg, ignore_unknown_fields=True)
    except json_format.ParseError:
        # Fallback tolerante: por campo, silenciando los que no encajen
        for f in msg.DESCRIPTOR.fields:
            raw = _read_field(source, f.name)
            if raw is None:
                continue
            try:
                _set_field(msg, f, raw)
            except (TypeError, ValueError):
                continue


def _set_field(msg: Any, field: Any, value: Any) -> None:
    if field.type == FD.TYPE_ENUM:
        if isinstance(value, str):
            enum_val = field.enum_type.values_by_name[value].number
        else:
            enum_val = int(value)
        setattr(msg, field.name, enum_val)
        return
    if field.type == FD.TYPE_BOOL:
        setattr(msg, field.name, bool(value))
        return
    if field.type in (
        FD.TYPE_UINT32, FD.TYPE_INT32, FD.TYPE_UINT64, FD.TYPE_INT64,
        FD.TYPE_FIXED32, FD.TYPE_FIXED64, FD.TYPE_SFIXED32, FD.TYPE_SFIXED64,
        FD.TYPE_SINT32, FD.TYPE_SINT64,
    ):
        setattr(msg, field.name, int(value))
        return
    if field.type in (FD.TYPE_FLOAT, FD.TYPE_DOUBLE):
        setattr(msg, field.name, float(value))
        return
    if field.type == FD.TYPE_STRING:
        setattr(msg, field.name, str(value))
        return
    if field.type == FD.TYPE_BYTES:
        if isinstance(value, str):
            import base64

            setattr(msg, field.name, base64.b64decode(value))
        else:
            setattr(msg, field.name, bytes(value))
        return
    # Campos MESSAGE / REPEATED no editables desde el editor genérico
    raise ValueError(f"unsupported field type for '{field.name}'")


def _apply_values(section_msg: Any, values: dict[str, Any]) -> None:
    for name, value in values.items():
        field = section_msg.DESCRIPTOR.fields_by_name.get(name)
        if field is None:
            raise ValueError(f"unknown field '{name}' in {section_msg.DESCRIPTOR.name}")
        _set_field(section_msg, field, value)


def _previous_section_dict(previous: dict[str, Any] | None, section: str) -> dict[str, Any]:
    if not isinstance(previous, dict):
        return {}
    inner = previous.get(section)
    return inner if isinstance(inner, dict) else {}


def build_config_set(params: dict[str, Any], previous: dict[str, Any] | None = None) -> Any:
    """Fusiona el estado anterior de la sección con los `values` pedidos.

    Sin este merge los campos no tocados se irían a default (el firmware
    reemplaza la sección entera al recibir set_config).
    """
    section = params["section"]
    values = params["values"]
    msg = admin_pb2.AdminMessage()
    section_msg = getattr(msg.set_config, section)
    _fill_message_from_dict(section_msg, _previous_section_dict(previous, section))
    _apply_values(section_msg, values)
    return msg


def build_module_config_set(params: dict[str, Any], previous: dict[str, Any] | None = None) -> Any:
    section = params["section"]
    values = params["values"]
    msg = admin_pb2.AdminMessage()
    section_msg = getattr(msg.set_module_config, section)
    _fill_message_from_dict(section_msg, _previous_section_dict(previous, section))
    _apply_values(section_msg, values)
    return msg


def _proto_section(section: str, kind: str) -> Any:
    if kind == "config":
        return getattr(config_pb2.Config(), section)
    return getattr(module_config_pb2.ModuleConfig(), section)


def _values_match(field: Any, requested: Any, read_value: Any) -> bool:
    if field.type == FD.TYPE_ENUM:
        if isinstance(read_value, str):
            expected = str(requested) if isinstance(requested, str) else field.enum_type.values_by_number[
                int(requested)
            ].name
            return read_value == expected
        expected_num = (
            field.enum_type.values_by_name[requested].number
            if isinstance(requested, str)
            else int(requested)
        )
        return int(read_value) == expected_num
    if field.type == FD.TYPE_BOOL:
        return bool(read_value) == bool(requested)
    if field.type in (FD.TYPE_FLOAT, FD.TYPE_DOUBLE):
        return abs(float(read_value) - float(requested)) < 1e-4
    if field.type == FD.TYPE_STRING:
        return str(read_value) == str(requested)
    if field.type == FD.TYPE_BYTES:
        return read_value == requested
    return int(read_value) == int(requested)


def compare_section(params: dict[str, Any], read: dict[str, Any], kind: str) -> bool:
    section = params["section"]
    values = params["values"]
    # La sección puede venir como {} legítimo cuando todo son defaults proto3;
    # solo la ausencia total (None / no está la clave) impide comparar
    if not isinstance(read, dict) or section not in read:
        return False
    raw = read[section]
    section_dict = raw if isinstance(raw, dict) else {}
    proto_section = _proto_section(section, kind)
    fields_by_name = proto_section.DESCRIPTOR.fields_by_name
    for name, requested in values.items():
        field = fields_by_name.get(name)
        if field is None:
            return False
        read_value = _read_field(section_dict, name)
        # Los defaults en proto3 pueden omitirse en asDict; ausencia == default
        if read_value is None:
            read_value = getattr(proto_section, name)
        if not _values_match(field, requested, read_value):
            return False
    return True


def compare_config(params: dict[str, Any], read: dict[str, Any]) -> bool:
    return compare_section(params, read, "config")


def compare_module_config(params: dict[str, Any], read: dict[str, Any]) -> bool:
    return compare_section(params, read, "module_config")


# ── Registro dinámico de SETs verificables ───────────────────────────────────


@dataclass(frozen=True)
class SetOperation:
    """Especificación de un SET verificable.

    - build_set(params, previous_read) -> AdminMessage. El previous_read es el
      resultado del GET previo (auditoría + passkey PKC + merge en M1.4).
    - verify_get(params) -> (op_type, params). Puede depender de params (p. ej.
      la sección) para elegir la lectura correcta.
    - compare(params, verified_read) -> bool.
    """

    build_set: Callable[[dict[str, Any], dict[str, Any] | None], Any]
    verify_get: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]
    compare: Callable[[dict[str, Any], dict[str, Any]], bool]


SET_OPERATIONS: dict[str, SetOperation] = {
    "owner.set": SetOperation(
        build_set=build_owner_set,
        verify_get=lambda _p: ("nodeinfo.get", {}),
        compare=compare_owner,
    ),
    "position.set_fixed": SetOperation(
        build_set=build_fixed_position_set,
        verify_get=lambda _p: ("config.get", {"section": "position"}),
        compare=compare_fixed_position,
    ),
    "config.set": SetOperation(
        build_set=build_config_set,
        verify_get=lambda p: ("config.get", {"section": p["section"]}),
        compare=compare_config,
    ),
    "module_config.set": SetOperation(
        build_set=build_module_config_set,
        verify_get=lambda p: ("module_config.get", {"section": p["section"]}),
        compare=compare_module_config,
    ),
}
