"""Construcción de peticiones AdminMessage (GET, M1.1) — módulo acoplado a la
librería oficial, como el resto de gateway/decoder (ADR 0009)."""

from typing import Any

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
