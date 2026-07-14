"""Entidades del sistema de autenticación de MeshSentinel.

Sin RBAC: `AuthUser.is_admin` es el único privilegio especial (gestión de
usuarios). Cualquier usuario autenticado puede realizar cualquier operación
sobre la red — la única diferencia entre usuarios es de identidad, no de
permisos.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class AuthUser:
    username: str
    display_name: str
    password_hash: str
    is_admin: bool = False
    enabled: bool = True
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None


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
