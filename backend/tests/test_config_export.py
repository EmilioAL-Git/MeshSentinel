from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from noc.adapters.persistence.alert_repositories import (
    SqlAlertRuleRepository,
    SqlNotificationChannelRepository,
    SqlNotificationProviderRepository,
)
from noc.adapters.persistence.config_export import export_config, import_config
from noc.adapters.persistence.database import Base
from noc.adapters.persistence.organization_repositories import SqlGroupRepository, SqlTagRepository
from noc.adapters.persistence.profile_repositories import SqlConfigProfileRepository
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.domain.admin.entities import ConfigProfile
from noc.domain.alerts.entities import AlertRule, NotificationChannel, NotificationProviderConfig
from noc.domain.nodes.entities import Group, Tag


async def _fresh_session_factory(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/{name}.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_source(session_factory) -> None:
    async with session_factory() as session, session.begin():
        group = await SqlGroupRepository(session).create(Group(name="Sierra", is_critical=True))
        await SqlTagRepository(session).create(Tag(name="solar", color="#ffcc00"))
        provider = await SqlNotificationProviderRepository(session).create(
            NotificationProviderConfig(
                name="bot-telegram", provider="telegram", configuration={"bot_token": "x", "chat_id": "1"}
            )
        )
        channel = await SqlNotificationChannelRepository(session).create(
            NotificationChannel(name="Operadores", description="Turno", provider_ids=[provider.id])
        )
        # Regla global (exportable), una por grupo (exportable, referencia por nombre)
        # y una escopada a un nodo concreto (NO exportable: sujeto de esta malla).
        await SqlAlertRuleRepository(session).create(
            AlertRule(name="batería global", rule_type="low_battery", severity="WARNING", threshold=20)
        )
        await SqlAlertRuleRepository(session).create(
            AlertRule(
                name="batería sierra", rule_type="low_battery", severity="CRITICAL",
                threshold=15, group_id=group.id, channel_ids=[channel.id],
            )
        )
        await SqlAlertRuleRepository(session).create(
            AlertRule(name="batería nodo suelto", rule_type="low_battery", severity="WARNING", node_id="!00000001")
        )
        profile_repo = SqlConfigProfileRepository(session)
        profile = await profile_repo.create(ConfigProfile(name="Repetidor estándar"))
        await profile_repo.add_version(profile.id, {"lora": {"region": "EU_868"}}, "inicial")
        await SqlSystemSettingsRepository(session).upsert("nexus.command_prefix", "/jt", "test")
        await SqlSystemSettingsRepository(session).upsert("nexus.response_window_seconds", 45.0, "test")


async def test_export_import_round_trip(tmp_path, session_factory):
    await _seed_source(session_factory)
    async with session_factory() as session:
        bundle = await export_config(session)

    # La regla escopada a un nodo de ESTA malla no viaja
    assert [r["name"] for r in bundle["alert_rules"]] == ["batería global", "batería sierra"]
    scoped = next(r for r in bundle["alert_rules"] if r["name"] == "batería sierra")
    assert scoped["group_name"] == "Sierra"
    assert scoped["channel_names"] == ["Operadores"]

    target = await _fresh_session_factory(tmp_path, "target")
    async with target() as session:
        report = await import_config(session, bundle)
        await session.commit()

    assert report.created == {
        "groups": 1, "tags": 1, "notification_providers": 1, "notification_channels": 1,
        "alert_rules": 2, "config_profiles": 1,
    }
    assert report.skipped_existing == {}

    async with target() as session:
        rules = {r.name: r for r in await SqlAlertRuleRepository(session).list_all()}
        assert rules["batería sierra"].group_id is not None
        assert rules["batería sierra"].channel_ids
        groups = {g.name: g for g in await SqlGroupRepository(session).list_with_counts()}
        assert rules["batería sierra"].group_id == groups["Sierra"].id
        profiles = await SqlConfigProfileRepository(session).list_profiles()
        assert profiles[0].latest_version == 1
        version = await SqlConfigProfileRepository(session).get_version(profiles[0].id, 1)
        assert version is not None and version.sections == {"lora": {"region": "EU_868"}}
        nexus = await SqlSystemSettingsRepository(session).list_all()
        assert nexus["nexus.command_prefix"] == "/jt"
        assert nexus["nexus.response_window_seconds"] == 45.0

    # Reimportar sobre la misma instalación no duplica nada (idempotente)
    async with target() as session:
        report2 = await import_config(session, bundle)
        await session.commit()
    assert report2.created == {}
    assert report2.skipped_existing == {
        "groups": 1, "tags": 1, "notification_providers": 1, "notification_channels": 1,
        "alert_rules": 2, "config_profiles": 1,
    }
