"""Ajustes configurables del módulo JenTastic-Nexus (ADR 0027 §13)."""

import pytest

from noc.application.nexus_settings import (
    NexusSettingError,
    default_settings,
    merge_settings,
    validate_changes,
)


def test_default_settings_match_established_defaults() -> None:
    # Los valores por defecto deben coincidir con el comportamiento previo
    # del módulo (ventana de 30s, cadencia de escaneo de 2 min, prefijo
    # /nexus, -node por defecto) — un cambio aquí sería un cambio de
    # comportamiento por defecto, no solo de ajustes.
    d = default_settings()
    assert d["addressing_mode"] == "shortname"
    assert d["command_prefix"] == "/nexus"
    assert d["channel_name"] is None
    assert d["response_window_seconds"] == 30.0
    assert d["scan_cooldown_seconds"] == 120.0
    assert d["default_target_kind"] == "broadcast"
    assert d["default_gateway_id"] is None
    assert d["hidden_commands"] == []
    assert d["pinned_nodes"] == []
    assert d["templates"] == []


def test_merge_settings_ignores_unrelated_keys() -> None:
    # system_settings también guarda umbrales de settings_registry.py sin
    # el prefijo "nexus." — no deben colarse aquí.
    merged = merge_settings({"low_battery_percent": 15, "nexus.command_prefix": "/jt"})
    assert merged["command_prefix"] == "/jt"
    assert "low_battery_percent" not in merged


def test_validate_changes_rejects_unknown_key() -> None:
    with pytest.raises(NexusSettingError):
        validate_changes({"no_existe": 1})


def test_validate_changes_rejects_invalid_addressing_mode() -> None:
    with pytest.raises(NexusSettingError):
        validate_changes({"addressing_mode": "mac_address"})


def test_validate_changes_rejects_non_positive_window() -> None:
    with pytest.raises(NexusSettingError):
        validate_changes({"response_window_seconds": 0})
    with pytest.raises(NexusSettingError):
        validate_changes({"response_window_seconds": -5})


def test_validate_changes_prefixes_keys() -> None:
    validated = validate_changes({"command_prefix": "/jt", "catalog_collapsed_default": True})
    assert validated == {"nexus.command_prefix": "/jt", "nexus.catalog_collapsed_default": True}


def test_validate_changes_fails_entirely_on_first_bad_key() -> None:
    # Ningún cambio parcial: si una clave del lote es inválida, no se debe
    # aplicar ninguna (el router hace el upsert después de validar TODO).
    with pytest.raises(NexusSettingError):
        validate_changes({"command_prefix": "/jt", "response_window_seconds": -1})


def test_validate_pinned_nodes_requires_short_name() -> None:
    with pytest.raises(NexusSettingError):
        validate_changes({"pinned_nodes": [{"label": "sin nombre"}]})
    validated = validate_changes({"pinned_nodes": [{"short_name": "ABMO"}]})
    assert validated["nexus.pinned_nodes"] == [{"short_name": "ABMO", "label": "ABMO"}]


def test_validate_templates_requires_command() -> None:
    with pytest.raises(NexusSettingError):
        validate_changes({"templates": [{"label": "sin comando"}]})
    validated = validate_changes({"templates": [{"command": "SETCONFIG", "args": "NI 3600"}]})
    assert validated["nexus.templates"] == [{"label": "SETCONFIG", "command": "SETCONFIG", "args": "NI 3600"}]


def test_validate_hidden_commands_must_be_string_list() -> None:
    with pytest.raises(NexusSettingError):
        validate_changes({"hidden_commands": "REBOOT"})
    validated = validate_changes({"hidden_commands": ["REBOOT", "DELNODE"]})
    assert validated["nexus.hidden_commands"] == ["REBOOT", "DELNODE"]


def test_validate_channel_name_accepts_none_or_text() -> None:
    assert validate_changes({"channel_name": None}) == {"nexus.channel_name": None}
    assert validate_changes({"channel_name": "Ops"}) == {"nexus.channel_name": "Ops"}
    with pytest.raises(NexusSettingError):
        validate_changes({"channel_name": ""})
