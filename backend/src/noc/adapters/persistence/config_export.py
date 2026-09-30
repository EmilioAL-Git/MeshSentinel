"""Exportar/importar la CONFIGURACIÓN PORTABLE de una instalación a otra.

Alcance acordado con el usuario (no "todo el panel"): reglas de alerta +
canales/integraciones de notificación, perfiles de configuración,
definiciones de grupos y etiquetas, ajustes de JenTastic-Nexus. Deliberadamente
FUERA: gateways (hardware de esta instalación), nodos/NodeDB, historial
(alertas disparadas, operaciones, diario de actividad), usuarios — todo eso
es específico de esta instalación, no "configuración" reutilizable en otra.

Las reglas de alerta escopadas a un nodo concreto (`node_id`) tampoco se
exportan: su sujeto es un dispositivo de ESTA malla, sin sentido en otra.

Import = "sembrar una instalación nueva", no sincronizar dos ya vivas: cada
entidad con nombre único se crea SOLO si no existe ya (por nombre) — nunca
sobrescribe. Los ajustes de Nexus son la excepción (no son "entidades con
nombre", son overrides sueltos): se aplican siempre, mismo criterio que
`PATCH /nexus/settings`.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.alert_repositories import (
    SqlAlertRuleRepository,
    SqlNotificationChannelRepository,
    SqlNotificationProviderRepository,
)
from noc.adapters.persistence.organization_repositories import SqlGroupRepository, SqlTagRepository
from noc.adapters.persistence.profile_repositories import SqlConfigProfileRepository
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.nexus_settings import SETTING_PREFIX, NexusSettingError, validate_changes
from noc.domain.admin.entities import ConfigProfile
from noc.domain.alerts.entities import AlertRule, NotificationChannel, NotificationProviderConfig
from noc.domain.nodes.entities import Group, Tag

SCHEMA_VERSION = 1


@dataclass(slots=True)
class ConfigImportReport:
    created: dict[str, int] = field(default_factory=dict)
    skipped_existing: dict[str, int] = field(default_factory=dict)
    skipped_invalid: list[str] = field(default_factory=list)

    def add_created(self, key: str) -> None:
        self.created[key] = self.created.get(key, 0) + 1

    def add_skipped(self, key: str) -> None:
        self.skipped_existing[key] = self.skipped_existing.get(key, 0) + 1


async def export_config(session: AsyncSession) -> dict[str, Any]:
    groups = await SqlGroupRepository(session).list_with_counts()
    group_name_by_id = {g.id: g.name for g in groups}

    channels = await SqlNotificationChannelRepository(session).list_all()
    providers = await SqlNotificationProviderRepository(session).list_all()
    provider_name_by_id = {p.id: p.name for p in providers}
    channel_name_by_id = {c.id: c.name for c in channels}

    rules = [r for r in await SqlAlertRuleRepository(session).list_all() if r.node_id is None]

    profiles_out = []
    profile_repo = SqlConfigProfileRepository(session)
    for profile in await profile_repo.list_profiles():
        if profile.latest_version <= 0:
            continue  # perfil sin ninguna versión todavía: nada que exportar
        version = await profile_repo.get_version(profile.id, profile.latest_version)
        assert version is not None
        profiles_out.append(
            {
                "name": profile.name,
                "description": profile.description,
                "sections": version.sections,
                "comment": version.comment,
            }
        )

    nexus_overrides = await SqlSystemSettingsRepository(session).list_all()
    nexus_settings = {
        key[len(SETTING_PREFIX):]: value
        for key, value in nexus_overrides.items()
        if key.startswith(SETTING_PREFIX)
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "groups": [{"name": g.name, "kind": g.kind, "is_critical": g.is_critical} for g in groups],
        "tags": [{"name": t.name, "color": t.color} for t in await SqlTagRepository(session).list_all()],
        "notification_providers": [
            {
                "name": p.name,
                "provider": p.provider,
                "configuration": p.configuration,
                "enabled": p.enabled,
            }
            for p in providers
        ],
        "notification_channels": [
            {
                "name": c.name,
                "description": c.description,
                "provider_names": [provider_name_by_id[pid] for pid in c.provider_ids if pid in provider_name_by_id],
            }
            for c in channels
        ],
        "alert_rules": [
            {
                "name": r.name,
                "rule_type": r.rule_type,
                "severity": r.severity,
                "enabled": r.enabled,
                "threshold": r.threshold,
                "duration_seconds": r.duration_seconds,
                "cooldown_seconds": r.cooldown_seconds,
                "params": r.params,
                "group_name": group_name_by_id.get(r.group_id) if r.group_id is not None else None,
                "channel_names": [
                    channel_name_by_id[cid] for cid in r.channel_ids if cid in channel_name_by_id
                ],
            }
            for r in rules
        ],
        "config_profiles": profiles_out,
        "nexus_settings": nexus_settings,
    }


async def import_config(session: AsyncSession, data: dict[str, Any]) -> ConfigImportReport:
    report = ConfigImportReport()

    group_repo = SqlGroupRepository(session)
    existing_groups = {g.name: g for g in await group_repo.list_with_counts()}
    for item in data.get("groups", []):
        if item["name"] in existing_groups:
            report.add_skipped("groups")
            continue
        created = await group_repo.create(Group(name=item["name"], is_critical=bool(item.get("is_critical", False))))
        existing_groups[created.name] = created
        report.add_created("groups")

    tag_repo = SqlTagRepository(session)
    existing_tags = {t.name for t in await tag_repo.list_all()}
    for item in data.get("tags", []):
        if item["name"] in existing_tags:
            report.add_skipped("tags")
            continue
        await tag_repo.create(Tag(name=item["name"], color=item.get("color")))
        existing_tags.add(item["name"])
        report.add_created("tags")

    provider_repo = SqlNotificationProviderRepository(session)
    provider_by_name = {p.name: p for p in await provider_repo.list_all()}
    for item in data.get("notification_providers", []):
        if item["name"] in provider_by_name:
            report.add_skipped("notification_providers")
            continue
        created = await provider_repo.create(
            NotificationProviderConfig(
                name=item["name"],
                provider=item["provider"],
                configuration=item.get("configuration", {}),
                enabled=bool(item.get("enabled", True)),
            )
        )
        provider_by_name[created.name] = created
        report.add_created("notification_providers")

    channel_repo = SqlNotificationChannelRepository(session)
    channel_by_name = {c.name: c for c in await channel_repo.list_all()}
    for item in data.get("notification_channels", []):
        if item["name"] in channel_by_name:
            report.add_skipped("notification_channels")
            continue
        provider_ids = [
            provider_by_name[name].id
            for name in item.get("provider_names", [])
            if name in provider_by_name and provider_by_name[name].id is not None
        ]
        created = await channel_repo.create(
            NotificationChannel(name=item["name"], description=item.get("description"), provider_ids=provider_ids)
        )
        channel_by_name[created.name] = created
        report.add_created("notification_channels")

    rule_repo = SqlAlertRuleRepository(session)
    existing_rule_names = {r.name for r in await rule_repo.list_all()}
    for item in data.get("alert_rules", []):
        if item["name"] in existing_rule_names:
            report.add_skipped("alert_rules")
            continue
        group_name = item.get("group_name")
        group = existing_groups.get(group_name) if group_name else None
        channel_ids = [
            channel_by_name[name].id
            for name in item.get("channel_names", [])
            if name in channel_by_name and channel_by_name[name].id is not None
        ]
        await rule_repo.create(
            AlertRule(
                name=item["name"],
                rule_type=item["rule_type"],
                severity=item["severity"],
                enabled=bool(item.get("enabled", True)),
                threshold=item.get("threshold"),
                duration_seconds=item.get("duration_seconds"),
                cooldown_seconds=int(item.get("cooldown_seconds", 0)),
                params=item.get("params", {}),
                group_id=group.id if group else None,
                channel_ids=channel_ids,
            )
        )
        existing_rule_names.add(item["name"])
        report.add_created("alert_rules")

    profile_repo = SqlConfigProfileRepository(session)
    existing_profile_names = {p.name for p in await profile_repo.list_profiles()}
    for item in data.get("config_profiles", []):
        if item["name"] in existing_profile_names:
            report.add_skipped("config_profiles")
            continue
        created = await profile_repo.create(
            ConfigProfile(name=item["name"], description=item.get("description"))
        )
        await profile_repo.add_version(
            created.id, item.get("sections", {}), item.get("comment"), created_by="import"
        )
        existing_profile_names.add(item["name"])
        report.add_created("config_profiles")

    settings_repo = SqlSystemSettingsRepository(session)
    nexus_data = data.get("nexus_settings")
    if nexus_data:
        try:
            validated = validate_changes(nexus_data)
        except NexusSettingError as exc:
            report.skipped_invalid.append(f"nexus_settings: {exc}")
        else:
            for key, value in validated.items():
                await settings_repo.upsert(key, value, updated_by="import")

    return report
