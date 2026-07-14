"""Servicio de autenticación de MeshSentinel.

Sin RBAC (salvo `is_admin`, que solo gatea la gestión de usuarios). Modo
abierto/protegido sin flag de entorno: `is_protected_mode()` se deriva de si
existe al menos un `auth_users` con `is_admin=True` y `enabled=True` — si el
único admin se deshabilita/borra, el sistema vuelve a modo abierto entero (es
la válvula de seguridad contra bloqueos, no un error).
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import redis.asyncio as aioredis

from noc.adapters.persistence.auth_repositories import (
    SqlAuthLoginLogRepository,
    SqlAuthSessionRepository,
    SqlAuthUserRepository,
)
from noc.adapters.persistence.models import AdminBatchModel, AdminOperationModel
from noc.config import Settings
from noc.domain.auth.entities import AuthSession, AuthUser, LoginLogEntry

logger = logging.getLogger("noc.auth")

_BCRYPT_MAX_BYTES = 72


class AuthError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class SessionOutcome:
    user: AuthUser
    token: str
    expires_at: datetime


class AuthService:
    def __init__(
        self, session_factory, redis_url: str, settings: Settings, redis_client: Any | None = None
    ) -> None:
        self._session_factory = session_factory
        # `redis_client` inyectable (tests): evita depender de un Redis real
        # para probar rate limiting, igual que session_factory ya desacopla de
        # una BD real concreta.
        self._redis = redis_client if redis_client is not None else aioredis.from_url(redis_url, decode_responses=True)
        self._settings = settings
        self._protected_cache: bool | None = None

    async def close(self) -> None:
        await self._redis.aclose()

    def invalidate_protected_cache(self) -> None:
        self._protected_cache = None

    async def is_protected_mode(self) -> bool:
        if self._protected_cache is None:
            async with self._session_factory() as session:
                count = await SqlAuthUserRepository(session).count_enabled_admins()
            self._protected_cache = count > 0
        return self._protected_cache

    # ── Contraseñas ──────────────────────────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        raw = password.encode("utf-8")
        if len(raw) > _BCRYPT_MAX_BYTES:
            raise AuthError("password_too_long", "La contraseña es demasiado larga")
        return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], password_hash.encode("ascii"))
        except ValueError:
            return False

    def validate_password_policy(self, password: str) -> None:
        if len(password) < self._settings.password_min_length:
            raise AuthError(
                "weak_password",
                f"La contraseña debe tener al menos {self._settings.password_min_length} caracteres",
            )

    # ── Rate limiting de login (Redis) ──────────────────────────────────

    def _rl_keys(self, username: str, ip: str | None) -> tuple[str, str | None]:
        return f"auth:fail:user:{username.lower()}", (f"auth:fail:ip:{ip}" if ip else None)

    async def _check_rate_limit(self, username: str, ip: str | None) -> None:
        user_key, ip_key = self._rl_keys(username, ip)
        user_fails = int(await self._redis.get(user_key) or 0)
        if user_fails >= self._settings.login_rate_limit_per_username:
            raise AuthError("rate_limited", "Demasiados intentos fallidos para este usuario, inténtalo más tarde")
        if ip_key is not None:
            ip_fails = int(await self._redis.get(ip_key) or 0)
            if ip_fails >= self._settings.login_rate_limit_per_ip:
                raise AuthError("rate_limited", "Demasiados intentos fallidos desde esta IP, inténtalo más tarde")

    async def _record_failure(self, username: str, ip: str | None) -> None:
        window = self._settings.login_rate_limit_window_seconds
        user_key, ip_key = self._rl_keys(username, ip)
        pipe = self._redis.pipeline()
        pipe.incr(user_key)
        pipe.expire(user_key, window)
        if ip_key is not None:
            pipe.incr(ip_key)
            pipe.expire(ip_key, window)
        await pipe.execute()

    async def _reset_failures(self, username: str) -> None:
        user_key, _ = self._rl_keys(username, None)
        await self._redis.delete(user_key)

    # ── Login / logout ───────────────────────────────────────────────────

    async def login(self, username: str, password: str, ip: str | None, user_agent: str | None) -> SessionOutcome:
        async with self._session_factory() as session:
            users = SqlAuthUserRepository(session)
            logs = SqlAuthLoginLogRepository(session)

            try:
                await self._check_rate_limit(username, ip)
            except AuthError as exc:
                await logs.create(
                    LoginLogEntry(username=username, event="rate_limited", reason=exc.reason, ip=ip, user_agent=user_agent)
                )
                await session.commit()
                raise

            user = await users.get_by_username(username)
            if user is None or not self.verify_password(password, user.password_hash):
                await self._record_failure(username, ip)
                await logs.create(
                    LoginLogEntry(
                        username=username,
                        user_id=user.id if user else None,
                        event="login_failed",
                        reason="bad_credentials",
                        ip=ip,
                        user_agent=user_agent,
                    )
                )
                await session.commit()
                raise AuthError("bad_credentials", "Usuario o contraseña incorrectos")

            if not user.enabled:
                await logs.create(
                    LoginLogEntry(username=username, user_id=user.id, event="user_disabled", ip=ip, user_agent=user_agent)
                )
                await session.commit()
                raise AuthError("user_disabled", "Este usuario está deshabilitado")

            await self._reset_failures(username)
            now = datetime.now(timezone.utc)
            token = secrets.token_urlsafe(32)
            expires_at = now + timedelta(hours=self._settings.session_idle_hours)
            await SqlAuthSessionRepository(session).create(
                AuthSession(user_id=user.id or 0, token_hash=_hash_token(token), expires_at=expires_at, ip=ip, user_agent=user_agent)
            )
            assert user.id is not None
            await users.update_fields(user.id, {"last_login_at": now})
            await logs.create(
                LoginLogEntry(username=username, user_id=user.id, event="login_ok", ip=ip, user_agent=user_agent)
            )
            await session.commit()
            return SessionOutcome(user=user, token=token, expires_at=expires_at)

    async def logout(self, token: str, ip: str | None, user_agent: str | None) -> None:
        async with self._session_factory() as session:
            s = await SqlAuthSessionRepository(session).get_by_token_hash(_hash_token(token))
            if s is None:
                return
            user = await SqlAuthUserRepository(session).get(s.user_id)
            await SqlAuthSessionRepository(session).delete_by_token_hash(_hash_token(token))
            await SqlAuthLoginLogRepository(session).create(
                LoginLogEntry(
                    username=user.username if user else "?",
                    user_id=s.user_id,
                    event="logout",
                    ip=ip,
                    user_agent=user_agent,
                )
            )
            await session.commit()

    async def resolve_session(self, token: str) -> AuthUser | None:
        """Valida el token de la cookie, aplica expiración deslizante y
        devuelve el usuario (None si no hay sesión válida). Sesiones
        caducadas (deslizante o tope absoluto) se borran y se auditan."""
        async with self._session_factory() as session:
            sessions = SqlAuthSessionRepository(session)
            s = await sessions.get_by_token_hash(_hash_token(token))
            if s is None:
                return None
            now = datetime.now(timezone.utc)
            # SQLite devuelve datetimes naive (se asumen UTC, igual que
            # Node.is_online en el resto del proyecto) — normalizar antes de comparar.
            created_at = _as_utc(s.created_at) or now
            absolute_deadline = created_at + timedelta(days=self._settings.session_max_days)
            expires_at = _as_utc(s.expires_at)
            if now > expires_at or now > absolute_deadline:
                users = SqlAuthUserRepository(session)
                user = await users.get(s.user_id)
                await sessions.delete_by_token_hash(_hash_token(token))
                await SqlAuthLoginLogRepository(session).create(
                    LoginLogEntry(username=user.username if user else "?", user_id=s.user_id, event="session_expired")
                )
                await session.commit()
                return None

            user = await SqlAuthUserRepository(session).get(s.user_id)
            if user is None or not user.enabled:
                await sessions.delete_by_token_hash(_hash_token(token))
                await session.commit()
                return None

            new_expiry = min(now + timedelta(hours=self._settings.session_idle_hours), absolute_deadline)
            assert s.id is not None
            await sessions.touch(s.id, now, new_expiry)
            await session.commit()
            return user

    # ── Gestión de usuarios ──────────────────────────────────────────────

    async def create_user(self, username: str, display_name: str, password: str, is_admin: bool) -> AuthUser:
        self.validate_password_policy(password)
        async with self._session_factory() as session:
            users = SqlAuthUserRepository(session)
            if await users.get_by_username(username) is not None:
                raise AuthError("username_taken", "Ya existe un usuario con ese nombre")
            # Bootstrap (CAMBIO 6/7): el primer usuario del sistema es SIEMPRE
            # admin, sin que el creador lo pida — de lo contrario nadie podría
            # gestionar usuarios nunca (modo protegido exige un admin habilitado).
            first_user = await users.count_all() == 0
            user = await users.create(
                AuthUser(
                    username=username,
                    display_name=display_name,
                    password_hash=self.hash_password(password),
                    is_admin=is_admin or first_user,
                    enabled=True,
                )
            )
            await session.commit()
        self.invalidate_protected_cache()
        return user

    async def update_display_name(self, user_id: int, display_name: str) -> AuthUser | None:
        async with self._session_factory() as session:
            user = await SqlAuthUserRepository(session).update_fields(user_id, {"display_name": display_name})
            await session.commit()
            return user

    async def set_password(self, user_id: int, password: str) -> AuthUser | None:
        self.validate_password_policy(password)
        async with self._session_factory() as session:
            user = await SqlAuthUserRepository(session).update_fields(
                user_id, {"password_hash": self.hash_password(password)}
            )
            # Cambiar la contraseña invalida cualquier sesión existente.
            await SqlAuthSessionRepository(session).delete_for_user(user_id)
            await session.commit()
            return user

    async def set_enabled(self, user_id: int, enabled: bool) -> AuthUser | None:
        async with self._session_factory() as session:
            user = await SqlAuthUserRepository(session).update_fields(user_id, {"enabled": enabled})
            if not enabled:
                await SqlAuthSessionRepository(session).delete_for_user(user_id)
            await session.commit()
        self.invalidate_protected_cache()
        return user

    async def set_admin(self, user_id: int, is_admin: bool) -> AuthUser | None:
        async with self._session_factory() as session:
            user = await SqlAuthUserRepository(session).update_fields(user_id, {"is_admin": is_admin})
            await session.commit()
        self.invalidate_protected_cache()
        return user

    async def delete_user(self, user_id: int) -> bool:
        from sqlalchemy import update as sa_update

        async with self._session_factory() as session:
            await SqlAuthSessionRepository(session).delete_for_user(user_id)
            # Autoría ya congelada en actor_username/actor_display_name — solo
            # se libera la FK (SQLite no aplica ON DELETE SET NULL: mismo
            # patrón que el resto del proyecto para relaciones huérfanas).
            await session.execute(
                sa_update(AdminOperationModel).where(AdminOperationModel.actor_id == user_id).values(actor_id=None)
            )
            await session.execute(
                sa_update(AdminBatchModel).where(AdminBatchModel.actor_id == user_id).values(actor_id=None)
            )
            deleted = await SqlAuthUserRepository(session).delete(user_id)
            await session.commit()
        self.invalidate_protected_cache()
        return deleted

    async def list_users(self) -> list[AuthUser]:
        async with self._session_factory() as session:
            return await SqlAuthUserRepository(session).list_all()

    async def get_user(self, user_id: int) -> AuthUser | None:
        async with self._session_factory() as session:
            return await SqlAuthUserRepository(session).get(user_id)
