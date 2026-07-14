from dataclasses import fields
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import AuthLoginLogModel, AuthSessionModel, AuthUserModel
from noc.domain.auth.entities import AuthSession, AuthUser, LoginLogEntry


def _user(m: AuthUserModel) -> AuthUser:
    return AuthUser(**{f.name: getattr(m, f.name) for f in fields(AuthUser)})


def _session_entity(m: AuthSessionModel) -> AuthSession:
    return AuthSession(**{f.name: getattr(m, f.name) for f in fields(AuthSession)})


def _log_entry(m: AuthLoginLogModel) -> LoginLogEntry:
    return LoginLogEntry(**{f.name: getattr(m, f.name) for f in fields(LoginLogEntry)})


class SqlAuthUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user: AuthUser) -> AuthUser:
        now = datetime.now(timezone.utc)
        m = AuthUserModel(
            username=user.username,
            display_name=user.display_name,
            password_hash=user.password_hash,
            is_admin=user.is_admin,
            enabled=user.enabled,
            created_at=user.created_at or now,
            updated_at=user.updated_at or now,
            last_login_at=user.last_login_at,
        )
        self._session.add(m)
        await self._session.flush()
        return _user(m)

    async def get(self, user_id: int) -> AuthUser | None:
        m = await self._session.get(AuthUserModel, user_id)
        return _user(m) if m else None

    async def get_by_username(self, username: str) -> AuthUser | None:
        stmt = select(AuthUserModel).where(func.lower(AuthUserModel.username) == username.lower())
        m = (await self._session.scalars(stmt)).first()
        return _user(m) if m else None

    async def list_all(self) -> list[AuthUser]:
        stmt = select(AuthUserModel).order_by(AuthUserModel.username)
        rows = await self._session.scalars(stmt)
        return [_user(r) for r in rows]

    async def count_enabled_admins(self) -> int:
        stmt = select(func.count()).select_from(AuthUserModel).where(
            AuthUserModel.is_admin.is_(True), AuthUserModel.enabled.is_(True)
        )
        return int((await self._session.scalars(stmt)).one())

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(AuthUserModel)
        return int((await self._session.scalars(stmt)).one())

    async def update_fields(self, user_id: int, changes: dict) -> AuthUser | None:
        m = await self._session.get(AuthUserModel, user_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _user(m)

    async def delete(self, user_id: int) -> bool:
        m = await self._session.get(AuthUserModel, user_id)
        if m is None:
            return False
        await self._session.delete(m)
        await self._session.flush()
        return True


class SqlAuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, s: AuthSession) -> AuthSession:
        now = datetime.now(timezone.utc)
        m = AuthSessionModel(
            user_id=s.user_id,
            token_hash=s.token_hash,
            created_at=s.created_at or now,
            last_seen_at=s.last_seen_at or now,
            expires_at=s.expires_at,
            ip=s.ip,
            user_agent=s.user_agent,
        )
        self._session.add(m)
        await self._session.flush()
        return _session_entity(m)

    async def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        stmt = select(AuthSessionModel).where(AuthSessionModel.token_hash == token_hash)
        m = (await self._session.scalars(stmt)).first()
        return _session_entity(m) if m else None

    async def touch(self, session_id: int, last_seen_at: datetime, expires_at: datetime) -> None:
        m = await self._session.get(AuthSessionModel, session_id)
        if m is not None:
            m.last_seen_at = last_seen_at
            m.expires_at = expires_at

    async def delete_by_token_hash(self, token_hash: str) -> bool:
        stmt = delete(AuthSessionModel).where(AuthSessionModel.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def delete_for_user(self, user_id: int) -> None:
        await self._session.execute(delete(AuthSessionModel).where(AuthSessionModel.user_id == user_id))


class SqlAuthLoginLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entry: LoginLogEntry) -> LoginLogEntry:
        m = AuthLoginLogModel(
            user_id=entry.user_id,
            username=entry.username,
            event=entry.event,
            reason=entry.reason,
            ip=entry.ip,
            user_agent=entry.user_agent,
            created_at=entry.created_at or datetime.now(timezone.utc),
        )
        self._session.add(m)
        await self._session.flush()
        return _log_entry(m)

    async def list_page(self, limit: int, before_id: int | None) -> list[LoginLogEntry]:
        stmt = select(AuthLoginLogModel).order_by(AuthLoginLogModel.id.desc()).limit(limit)
        if before_id is not None:
            stmt = stmt.where(AuthLoginLogModel.id < before_id)
        rows = await self._session.scalars(stmt)
        return [_log_entry(r) for r in rows]
