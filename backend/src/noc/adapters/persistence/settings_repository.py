from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import SystemSettingModel


class SqlSystemSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> dict[str, Any]:
        rows = (await self._session.execute(select(SystemSettingModel))).scalars().all()
        return {m.key: m.value for m in rows}

    async def upsert(self, key: str, value: Any, updated_by: str | None) -> None:
        m = await self._session.get(SystemSettingModel, key)
        now = datetime.now(timezone.utc)
        if m is None:
            self._session.add(
                SystemSettingModel(key=key, value=value, updated_at=now, updated_by=updated_by)
            )
        else:
            m.value = value
            m.updated_at = now
            m.updated_by = updated_by

    async def reset(self, key: str) -> None:
        await self._session.execute(delete(SystemSettingModel).where(SystemSettingModel.key == key))
