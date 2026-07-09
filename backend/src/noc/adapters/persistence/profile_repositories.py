"""Persistencia de perfiles de configuración (M3).

Los perfiles son metadatos + versiones inmutables: editar el contenido crea
una versión nueva (append-only, como las series temporales del proyecto).
SQLite no aplica ON DELETE CASCADE → los borrados de versiones son explícitos.
"""

from dataclasses import fields
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import ConfigProfileModel, ConfigProfileVersionModel
from noc.domain.admin.entities import ConfigProfile, ConfigProfileVersion


def _profile_entity(m: ConfigProfileModel, latest_version: int = 0) -> ConfigProfile:
    return ConfigProfile(
        id=m.id,
        name=m.name,
        description=m.description,
        created_at=m.created_at,
        updated_at=m.updated_at,
        latest_version=latest_version,
    )


def _version_entity(m: ConfigProfileVersionModel) -> ConfigProfileVersion:
    return ConfigProfileVersion(
        **{f.name: getattr(m, f.name) for f in fields(ConfigProfileVersion)}
    )


class SqlConfigProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, profile: ConfigProfile) -> ConfigProfile:
        now = datetime.now(timezone.utc)
        m = ConfigProfileModel(
            name=profile.name,
            description=profile.description,
            created_at=profile.created_at or now,
            updated_at=profile.updated_at or now,
        )
        self._session.add(m)
        await self._session.flush()
        return _profile_entity(m)

    async def get(self, profile_id: int) -> ConfigProfile | None:
        m = await self._session.get(ConfigProfileModel, profile_id)
        if m is None:
            return None
        return _profile_entity(m, await self.latest_version_number(profile_id))

    async def get_by_name(self, name: str) -> ConfigProfile | None:
        m = await self._session.scalar(
            select(ConfigProfileModel).where(ConfigProfileModel.name == name)
        )
        if m is None:
            return None
        return _profile_entity(m, await self.latest_version_number(m.id))

    async def list_profiles(self) -> list[ConfigProfile]:
        latest = (
            select(
                ConfigProfileVersionModel.profile_id,
                func.max(ConfigProfileVersionModel.version).label("latest"),
            )
            .group_by(ConfigProfileVersionModel.profile_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(ConfigProfileModel, latest.c.latest)
            .join(latest, latest.c.profile_id == ConfigProfileModel.id, isouter=True)
            .order_by(ConfigProfileModel.name)
        )
        return [_profile_entity(m, int(v or 0)) for m, v in rows]

    async def update_fields(self, profile_id: int, changes: dict[str, Any]) -> ConfigProfile | None:
        m = await self._session.get(ConfigProfileModel, profile_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _profile_entity(m, await self.latest_version_number(profile_id))

    async def delete(self, profile_id: int) -> bool:
        m = await self._session.get(ConfigProfileModel, profile_id)
        if m is None:
            return False
        await self._session.execute(
            delete(ConfigProfileVersionModel).where(
                ConfigProfileVersionModel.profile_id == profile_id
            )
        )
        await self._session.delete(m)
        await self._session.flush()
        return True

    # ── Versiones ────────────────────────────────────────────────────────────

    async def latest_version_number(self, profile_id: int) -> int:
        result = await self._session.scalar(
            select(func.max(ConfigProfileVersionModel.version)).where(
                ConfigProfileVersionModel.profile_id == profile_id
            )
        )
        return int(result or 0)

    async def add_version(
        self,
        profile_id: int,
        sections: dict[str, dict[str, Any]],
        comment: str | None,
        created_by: str = "admin",
    ) -> ConfigProfileVersion:
        now = datetime.now(timezone.utc)
        next_version = await self.latest_version_number(profile_id) + 1
        m = ConfigProfileVersionModel(
            profile_id=profile_id,
            version=next_version,
            sections=sections,
            comment=comment,
            created_by=created_by,
            created_at=now,
        )
        self._session.add(m)
        # El perfil refleja cuándo cambió su contenido por última vez
        profile = await self._session.get(ConfigProfileModel, profile_id)
        if profile is not None:
            profile.updated_at = now
        await self._session.flush()
        return _version_entity(m)

    async def list_versions(self, profile_id: int) -> list[ConfigProfileVersion]:
        rows = await self._session.scalars(
            select(ConfigProfileVersionModel)
            .where(ConfigProfileVersionModel.profile_id == profile_id)
            .order_by(ConfigProfileVersionModel.version.desc())
        )
        return [_version_entity(r) for r in rows]

    async def get_version(self, profile_id: int, version: int) -> ConfigProfileVersion | None:
        m = await self._session.scalar(
            select(ConfigProfileVersionModel).where(
                ConfigProfileVersionModel.profile_id == profile_id,
                ConfigProfileVersionModel.version == version,
            )
        )
        return _version_entity(m) if m else None
