import pytest

from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.settings_registry import (
    SETTINGS_BY_KEY,
    SETTINGS_REGISTRY,
    SettingValidationError,
    apply_overrides,
    coerce_value,
)
from noc.config import Settings


def test_registry_keys_match_settings_fields() -> None:
    settings = Settings(_env_file=None)
    for spec in SETTINGS_REGISTRY:
        assert hasattr(settings, spec.key), f"{spec.key} no existe en Settings"


def test_coerce_value_casts_int_and_float() -> None:
    assert coerce_value(SETTINGS_BY_KEY["node_offline_after_seconds"], 120.0) == 120
    assert isinstance(coerce_value(SETTINGS_BY_KEY["node_offline_after_seconds"], 120.0), int)
    assert coerce_value(SETTINGS_BY_KEY["snr_degraded_threshold"], -12) == -12.0
    assert isinstance(coerce_value(SETTINGS_BY_KEY["snr_degraded_threshold"], -12), float)


def test_coerce_value_rejects_below_minimum() -> None:
    with pytest.raises(SettingValidationError):
        coerce_value(SETTINGS_BY_KEY["node_offline_after_seconds"], 5)


def test_coerce_value_rejects_non_numeric() -> None:
    with pytest.raises(SettingValidationError):
        coerce_value(SETTINGS_BY_KEY["node_offline_after_seconds"], "900")
    with pytest.raises(SettingValidationError):
        coerce_value(SETTINGS_BY_KEY["node_offline_after_seconds"], True)


def test_apply_overrides_mutates_shared_settings_instance() -> None:
    settings = Settings(_env_file=None)
    apply_overrides(settings, {"node_offline_after_seconds": 600, "low_battery_threshold": 15})
    assert settings.node_offline_after_seconds == 600
    assert settings.low_battery_threshold == 15


def test_apply_overrides_ignores_unknown_and_invalid_keys() -> None:
    settings = Settings(_env_file=None)
    baseline = settings.node_offline_after_seconds
    apply_overrides(settings, {"not_a_real_setting": 1, "node_offline_after_seconds": "bogus"})
    assert settings.node_offline_after_seconds == baseline


async def test_settings_repository_upsert_list_reset(session_factory) -> None:  # type: ignore[no-untyped-def]
    async with session_factory() as session:
        repo = SqlSystemSettingsRepository(session)
        assert await repo.list_all() == {}

        await repo.upsert("node_offline_after_seconds", 600, "alice")
        await session.commit()

    async with session_factory() as session:
        repo = SqlSystemSettingsRepository(session)
        overrides = await repo.list_all()
        assert overrides == {"node_offline_after_seconds": 600}

        await repo.upsert("node_offline_after_seconds", 700, "bob")
        await session.commit()

    async with session_factory() as session:
        repo = SqlSystemSettingsRepository(session)
        assert (await repo.list_all())["node_offline_after_seconds"] == 700

        await repo.reset("node_offline_after_seconds")
        await session.commit()

    async with session_factory() as session:
        assert await SqlSystemSettingsRepository(session).list_all() == {}
