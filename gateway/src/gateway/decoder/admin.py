"""Construcción de peticiones AdminMessage (GET M1.1, SET verificables M1.3) —
módulo acoplado a la librería oficial, como el resto de gateway/decoder
(ADR 0009)."""

from dataclasses import dataclass
from typing import Any, Callable

from meshtastic.protobuf import admin_pb2

CONFIG_SECTION_TO_ENUM = {
    "device": "DEVICE_CONFIG",
    "position": "POSITION_CONFIG",
    "power": "POWER_CONFIG",
    "network": "NETWORK_CONFIG",
    "display": "DISPLAY_CONFIG",
    "lora": "LORA_CONFIG",
    "bluetooth": "BLUETOOTH_CONFIG",
    "security": "SECURITY_CONFIG",
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
}


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


def build_owner_set(params: dict[str, Any]) -> Any:
    msg = admin_pb2.AdminMessage()
    # Solo los campos presentes: el firmware ignora los vacíos en set_owner
    if params.get("short_name") is not None:
        msg.set_owner.short_name = params["short_name"]
    if params.get("long_name") is not None:
        msg.set_owner.long_name = params["long_name"]
    return msg


def compare_owner(requested: dict[str, Any], read: dict[str, Any]) -> bool:
    """El read-back (getOwnerResponse) debe reflejar exactamente lo pedido."""
    if "short_name" in requested and read.get("shortName") != requested["short_name"]:
        return False
    if "long_name" in requested and read.get("longName") != requested["long_name"]:
        return False
    return True


def build_fixed_position_set(params: dict[str, Any]) -> Any:
    msg = admin_pb2.AdminMessage()
    msg.set_fixed_position.latitude_i = int(round(params["latitude"] * 1e7))
    msg.set_fixed_position.longitude_i = int(round(params["longitude"] * 1e7))
    if params.get("altitude") is not None:
        msg.set_fixed_position.altitude = int(params["altitude"])
    return msg


def compare_fixed_position(requested: dict[str, Any], read: dict[str, Any]) -> bool:  # noqa: ARG001
    """Las coordenadas no son legibles por admin GET: la confirmación posible es
    que POSITION_CONFIG refleje fixedPosition=true tras el SET."""
    position = read.get("position") if isinstance(read.get("position"), dict) else {}
    return bool(position.get("fixedPosition"))


@dataclass(frozen=True)
class SetOperation:
    """Especificación de un SET verificable: construir SET, construir GET de
    lectura (previa y de verificación) y comparar lo leído con lo pedido."""

    build_set: Callable[[dict[str, Any]], Any]
    verify_get: tuple[str, dict[str, Any]]  # (operation_type GET, params GET)
    compare: Callable[[dict[str, Any], dict[str, Any]], bool]


SET_OPERATIONS: dict[str, SetOperation] = {
    "owner.set": SetOperation(
        build_set=build_owner_set,
        verify_get=("nodeinfo.get", {}),
        compare=compare_owner,
    ),
    "position.set_fixed": SetOperation(
        build_set=build_fixed_position_set,
        verify_get=("config.get", {"section": "position"}),
        compare=compare_fixed_position,
    ),
}
