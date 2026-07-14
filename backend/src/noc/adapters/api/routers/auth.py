"""API de autenticación de MeshSentinel.

Monitorización siempre abierta; solo las acciones que modifican la red
(Tier A/B en el resto de routers) exigen `RequireAuthDep`. Sin RBAC — la
única excepción es `is_admin`, que gatea exclusivamente la gestión de
usuarios (`RequireAdminDep`), nunca las operaciones sobre la red.
"""

from dataclasses import fields
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from noc.adapters.api.deps import CurrentUserDep, RequireAdminDep, RequireAuthDep
from noc.adapters.persistence.auth_repositories import SqlAuthLoginLogRepository
from noc.adapters.persistence.database import Database
from noc.application.auth.service import AuthError, AuthService
from noc.config import get_settings
from noc.domain.auth.entities import AuthUser

router = APIRouter(prefix="/auth", tags=["auth"])


def _service(request: Request) -> AuthService:
    return request.app.state.auth


def _db(request: Request) -> Database:
    return request.app.state.db


def _client_ip(request: Request) -> str | None:
    # nginx (frontend/nginx.conf) siempre fija X-Real-IP; sin proxy delante
    # (dev directo contra uvicorn) se usa la IP de socket.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool
    enabled: bool
    created_at: datetime | None
    updated_at: datetime | None
    last_login_at: datetime | None

    @classmethod
    def from_entity(cls, u: AuthUser) -> "UserOut":
        return cls(**{f.name: getattr(u, f.name) for f in fields(AuthUser) if f.name != "password_hash"})


class MeOut(BaseModel):
    authenticated: bool
    protected_mode: bool
    user: UserOut | None


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    is_admin: bool = False


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    is_admin: bool | None = None


class DisplayNameIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class EnabledIn(BaseModel):
    enabled: bool


class LoginLogOut(BaseModel):
    id: int
    user_id: int | None
    username: str
    event: str
    reason: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime | None


def _set_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    settings = get_settings()
    max_age = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


@router.get("/me", response_model=MeOut)
async def me(request: Request, current_user: CurrentUserDep) -> MeOut:
    protected = await _service(request).is_protected_mode()
    return MeOut(
        authenticated=current_user is not None,
        protected_mode=protected,
        user=UserOut.from_entity(current_user) if current_user else None,
    )


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response) -> UserOut:
    try:
        outcome = await _service(request).login(
            body.username, body.password, _client_ip(request), request.headers.get("user-agent")
        )
    except AuthError as exc:
        status_code = 429 if exc.reason == "rate_limited" else 401
        raise HTTPException(status_code=status_code, detail=exc.message) from exc
    _set_session_cookie(response, outcome.token, outcome.expires_at)
    return UserOut.from_entity(outcome.user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await _service(request).logout(token, _client_ip(request), request.headers.get("user-agent"))
    response.delete_cookie(key=settings.session_cookie_name, path="/")


@router.patch("/me", response_model=UserOut)
async def update_me(body: DisplayNameIn, request: Request, current_user: RequireAuthDep) -> UserOut:
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = await _service(request).update_display_name(current_user.id or 0, body.display_name)
    assert user is not None
    return UserOut.from_entity(user)


@router.put("/me/password", status_code=204)
async def change_own_password(body: PasswordIn, request: Request, current_user: RequireAuthDep) -> None:
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        await _service(request).set_password(current_user.id or 0, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


# ── Gestión de usuarios (CAMBIO 7: solo is_admin, sin más RBAC) ────────────


@router.get("/users", response_model=list[UserOut])
async def list_users(request: Request, _admin: RequireAdminDep) -> list[UserOut]:
    users = await _service(request).list_users()
    return [UserOut.from_entity(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreateIn, request: Request, _admin: RequireAdminDep) -> UserOut:
    try:
        user = await _service(request).create_user(body.username, body.display_name, body.password, body.is_admin)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return UserOut.from_entity(user)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdateIn, request: Request, _admin: RequireAdminDep) -> UserOut:
    service = _service(request)
    user = await service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.display_name is not None:
        user = await service.update_display_name(user_id, body.display_name)
    if body.is_admin is not None:
        user = await service.set_admin(user_id, body.is_admin)
    assert user is not None
    return UserOut.from_entity(user)


@router.put("/users/{user_id}/enabled", response_model=UserOut)
async def set_user_enabled(user_id: int, body: EnabledIn, request: Request, _admin: RequireAdminDep) -> UserOut:
    user = await _service(request).set_enabled(user_id, body.enabled)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.from_entity(user)


@router.put("/users/{user_id}/password", status_code=204)
async def set_user_password(user_id: int, body: PasswordIn, request: Request, _admin: RequireAdminDep) -> None:
    try:
        user = await _service(request).set_password(user_id, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, request: Request, _admin: RequireAdminDep) -> None:
    deleted = await _service(request).delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")


# ── Login log (CAMBIO 4) ────────────────────────────────────────────────────
# Contiene IPs y user-agents de intentos de login: a diferencia del resto de
# GET del sistema (siempre públicos, filosofía de monitorización abierta),
# esto es auditoría de seguridad de la propia autenticación — exige sesión,
# pero sin exigir is_admin (no es gestión de usuarios).


@router.get("/login-log", response_model=list[LoginLogOut])
async def login_log(
    request: Request,
    _user: RequireAuthDep,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None, ge=1),
) -> list[LoginLogOut]:
    async with _db(request).session_factory() as session:
        entries = await SqlAuthLoginLogRepository(session).list_page(limit, before_id)
    return [LoginLogOut(**{f.name: getattr(e, f.name) for f in fields(e)}) for e in entries]
