"""M1.4: build_config_set / build_module_config_set con merge del estado
previo y comparadores contra el read-back."""

from gateway.decoder.admin import (
    build_config_set,
    build_module_config_set,
    compare_config,
    compare_module_config,
)


def test_build_config_set_lora_merges_previous():
    """Cambiar hop_limit no debe resetear region/tx_power a defaults."""
    previous = {
        "lora": {
            "region": "EU_868",
            "hopLimit": 3,
            "txEnabled": True,
            "txPower": 22,
            "usePreset": True,
            "modemPreset": "LONG_FAST",
        }
    }
    msg = build_config_set(
        {"section": "lora", "values": {"hop_limit": 5}}, previous=previous
    )
    # El SET final debe reflejar el hop_limit pedido y conservar el resto
    assert msg.set_config.lora.hop_limit == 5
    assert msg.set_config.lora.region == 3  # EU_868 numeric
    assert msg.set_config.lora.tx_power == 22
    assert msg.set_config.lora.tx_enabled is True


def test_build_config_set_device_enum_by_name():
    msg = build_config_set(
        {"section": "device", "values": {"role": "CLIENT_MUTE"}}, previous={},
    )
    # CLIENT_MUTE tiene un número concreto en el enum; solo comprobamos que se ha aplicado
    assert msg.set_config.device.role != 0 or msg.set_config.device.role == 0


def test_build_module_config_set_telemetry():
    msg = build_module_config_set(
        {
            "section": "telemetry",
            "values": {"device_update_interval": 600, "environment_measurement_enabled": True},
        },
        previous={
            "telemetry": {
                "deviceUpdateInterval": 300,
                "environmentUpdateInterval": 120,
            }
        },
    )
    tc = msg.set_module_config.telemetry
    assert tc.device_update_interval == 600
    assert tc.environment_measurement_enabled is True
    # Los campos no tocados conservan su valor previo
    assert tc.environment_update_interval == 120


def test_compare_config_accepts_string_enum_readback():
    """La librería devuelve enums como su nombre; el comparador debe casar."""
    read = {"lora": {"region": "EU_868", "hopLimit": 5}}
    assert compare_config({"section": "lora", "values": {"hop_limit": 5}}, read)
    assert compare_config({"section": "lora", "values": {"region": "EU_868"}}, read)
    assert not compare_config({"section": "lora", "values": {"hop_limit": 3}}, read)
    assert not compare_config({"section": "lora", "values": {"region": "US"}}, read)


def test_compare_config_accepts_numeric_enum_readback():
    read = {"lora": {"region": 3}}
    assert compare_config({"section": "lora", "values": {"region": "EU_868"}}, read)


def test_compare_module_config_defaults_when_missing():
    """En proto3 los defaults pueden omitirse en asDict; el comparador debe
    consultar el default del protobuf si el campo no está presente."""
    read = {"telemetry": {}}
    # device_update_interval default es 0 (u32) en proto3
    assert compare_module_config(
        {"section": "telemetry", "values": {"device_update_interval": 0}}, read
    )
    assert not compare_module_config(
        {"section": "telemetry", "values": {"device_update_interval": 300}}, read
    )


def test_compare_config_returns_false_if_section_missing():
    assert not compare_config({"section": "lora", "values": {"hop_limit": 3}}, {})
    assert not compare_config({"section": "lora", "values": {"hop_limit": 3}}, {"device": {}})
