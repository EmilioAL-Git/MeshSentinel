"""Entidades del sistema de autenticación de MeshSentinel.

Roles (ADR 0029): `admin` (todo), `manager` (todo salvo gestión de usuarios y
ajustes de gateways) y `user` (solo lectura + sus favoritos y su grupo
personal). Sin sesión: comportamiento previo (modo abierto/solo lectura).
"""

from dataclasses import dataclass
from datetime import datetime


ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_USER)


@dataclass(slots=True)
class AuthUser:
    username: str
    display_name: str
    password_hash: str
    role: str = ROLE_MANAGER
    enabled: bool = True
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_manage(self) -> bool:
        """Gestor o admin: puede actuar sobre la red."""
        return self.role in (ROLE_ADMIN, ROLE_MANAGER)


@dataclass(slots=True)
class AuthSession:
    user_id: int
    token_hash: str
    expires_at: datetime
    id: int | None = None
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None


# Eventos de auth_login_log (CAMBIO 4 del diseño): login correcto/fallido,
# logout, expiración de sesión, usuario deshabilitado, bloqueo por rate limit.
LoginLogEvent = str  # "login_ok" | "login_failed" | "logout" | "session_expired" | "user_disabled" | "rate_limited"


@dataclass(slots=True)
class LoginLogEntry:
    username: str
    event: LoginLogEvent
    user_id: int | None = None
    reason: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    id: int | None = None
    created_at: datetime | None = None
