"""Tests del sistema de autenticación (auth_users/auth_sessions/auth_login_log).

Redis se sustituye por un fake en memoria (mismo subset usado por
AuthService: get/delete/pipeline incr+expire) — evita depender de un Redis
real para probar rate limiting, igual que session_factory ya desacopla de
una BD real concreta en el resto de la suite.
"""

from datetime import datetime, timedelta, timezone

import pytest

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.auth_repositories import SqlAuthLoginLogRepository, SqlAuthSessionRepository
from noc.application.auth.actor import ActorContext, resolve_actor_label
from noc.application.auth.service import AuthError, AuthService
from noc.config import Settings
from noc.domain.admin.entities import AdminOperation


class FakePipeline:
    def __init__(self, store: dict[str, int]) -> None:
        self._store = store
        self._incrs: list[str] = []

    def incr(self, key: str) -> "FakePipeline":
        self._incrs.append(key)
        return self

    def expire(self, key: str, ttl: int) -> "FakePipeline":
        return self

    async def execute(self) -> None:
        for key in self._incrs:
            self._store[key] = self._store.get(key, 0) + 1
        self._incrs = []


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def get(self, key: str) -> int | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.store)

    async def aclose(self) -> None:
        pass


def make_service(session_factory, **overrides) -> AuthService:
    settings = Settings(_env_file=None, **overrides)
    return AuthService(session_factory, "redis://unused", settings, redis_client=FakeRedis())


# ── AuthService: modo abierto/protegido ─────────────────────────────────────


async def test_open_mode_until_first_admin(session_factory):
    service = make_service(session_factory)
    assert await service.is_protected_mode() is False

    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=False)
    # CAMBIO 6/7: el primer usuario es SIEMPRE admin, aunque no se pida.
    assert await service.is_protected_mode() is True

    users = await service.list_users()
    assert users[0].is_admin is True


async def test_open_mode_returns_when_last_admin_disabled(session_factory):
    service = make_service(session_factory)
    admin = await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    assert await service.is_protected_mode() is True

    await service.set_enabled(admin.id, False)
    assert await service.is_protected_mode() is False


# ── Login / logout / sesión deslizante ──────────────────────────────────────


async def test_login_success_sets_session(session_factory):
    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)

    outcome = await service.login("ealfaro", "correcto-y-largo", "127.0.0.1", "pytest")
    assert outcome.user.username == "ealfaro"

    resolved = await service.resolve_session(outcome.token)
    assert resolved is not None
    assert resolved.username == "ealfaro"
    assert resolved.last_login_at is not None


async def test_login_wrong_password_fails_and_logs(session_factory):
    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)

    with pytest.raises(AuthError) as exc:
        await service.login("ealfaro", "incorrecta", None, None)
    assert exc.value.reason == "bad_credentials"


async def test_login_disabled_user_fails(session_factory):
    service = make_service(session_factory)
    user = await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    await service.set_enabled(user.id, False)

    with pytest.raises(AuthError) as exc:
        await service.login("ealfaro", "correcto-y-largo", None, None)
    assert exc.value.reason == "user_disabled"


async def test_login_rate_limited_after_failures(session_factory):
    service = make_service(session_factory, login_rate_limit_per_username=3)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)

    for _ in range(3):
        with pytest.raises(AuthError):
            await service.login("ealfaro", "mala", "1.2.3.4", None)

    with pytest.raises(AuthError) as exc:
        await service.login("ealfaro", "correcto-y-largo", "1.2.3.4", None)
    assert exc.value.reason == "rate_limited"


async def test_login_success_resets_failure_counter(session_factory):
    service = make_service(session_factory, login_rate_limit_per_username=3)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)

    with pytest.raises(AuthError):
        await service.login("ealfaro", "mala", None, None)
    outcome = await service.login("ealfaro", "correcto-y-largo", None, None)
    assert outcome.user.username == "ealfaro"
    # El contador de fallos se reinició: dos fallos más no deberían bastar
    # para bloquear (el límite es 3).
    for _ in range(2):
        with pytest.raises(AuthError) as exc:
            await service.login("ealfaro", "mala", None, None)
        assert exc.value.reason == "bad_credentials"


async def test_logout_invalidates_session(session_factory):
    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    outcome = await service.login("ealfaro", "correcto-y-largo", None, None)

    await service.logout(outcome.token, None, None)
    assert await service.resolve_session(outcome.token) is None


async def test_expired_session_is_rejected_and_deleted(session_factory):
    service = make_service(session_factory, session_idle_hours=1)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    outcome = await service.login("ealfaro", "correcto-y-largo", None, None)

    # Simula el paso del tiempo forzando la expiración en BD directamente.
    import hashlib

    async with session_factory() as session:
        sessions = SqlAuthSessionRepository(session)
        s = await sessions.get_by_token_hash(hashlib.sha256(outcome.token.encode()).hexdigest())
        assert s is not None
        await sessions.touch(s.id, datetime.now(timezone.utc) - timedelta(hours=2), datetime.now(timezone.utc) - timedelta(hours=1))
        await session.commit()

    assert await service.resolve_session(outcome.token) is None

    async with session_factory() as session:
        entries = await SqlAuthLoginLogRepository(session).list_page(10, None)
    assert any(e.event == "session_expired" for e in entries)


async def test_set_password_invalidates_existing_sessions(session_factory):
    service = make_service(session_factory)
    user = await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    outcome = await service.login("ealfaro", "correcto-y-largo", None, None)

    await service.set_password(user.id, "otra-contrasena-larga")
    assert await service.resolve_session(outcome.token) is None


async def test_login_unknown_user_raises_bad_credentials(session_factory):
    # Además de fallar, recorre la rama del hash de sacrificio (timing):
    # el username inexistente paga el mismo coste bcrypt que uno real.
    service = make_service(session_factory)
    with pytest.raises(AuthError) as exc:
        await service.login("no-existe", "cualquier-cosa-larga", None, None)
    assert exc.value.reason == "bad_credentials"


def test_verify_password_rejects_over_bcrypt_limit():
    # hash_password rechaza >72 bytes, así que verify no debe truncar (truncar
    # aceptaría cualquier sufijo tras el byte 72).
    h = AuthService.hash_password("x" * 72)
    assert AuthService.verify_password("x" * 72, h) is True
    assert AuthService.verify_password("x" * 73, h) is False


async def test_sliding_renewal_is_throttled(session_factory):
    """El touch deslizante solo escribe si el último tiene >1 min: dos
    resolves seguidos no cambian expires_at; con last_seen_at envejecido
    a mano, el siguiente resolve sí renueva."""
    import hashlib

    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    outcome = await service.login("ealfaro", "correcto-y-largo", None, None)
    token_hash = hashlib.sha256(outcome.token.encode()).hexdigest()

    assert await service.resolve_session(outcome.token) is not None
    async with session_factory() as session:
        s = await SqlAuthSessionRepository(session).get_by_token_hash(token_hash)
        first_expiry = s.expires_at

    assert await service.resolve_session(outcome.token) is not None
    async with session_factory() as session:
        s = await SqlAuthSessionRepository(session).get_by_token_hash(token_hash)
        assert s.expires_at == first_expiry  # sin escritura: throttled

    # Envejecer last_seen_at por encima del umbral manteniendo la sesión viva.
    async with session_factory() as session:
        sessions = SqlAuthSessionRepository(session)
        s = await sessions.get_by_token_hash(token_hash)
        await sessions.touch(s.id, datetime.now(timezone.utc) - timedelta(minutes=5), s.expires_at)
        await session.commit()

    assert await service.resolve_session(outcome.token) is not None
    async with session_factory() as session:
        s = await SqlAuthSessionRepository(session).get_by_token_hash(token_hash)
        assert s.expires_at != first_expiry  # renovada


async def test_login_prunes_expired_sessions_of_everyone(session_factory):
    import hashlib

    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    stale = await service.login("ealfaro", "correcto-y-largo", None, None)
    stale_hash = hashlib.sha256(stale.token.encode()).hexdigest()

    # Caducar la primera sesión en BD sin presentarla de nuevo.
    async with session_factory() as session:
        sessions = SqlAuthSessionRepository(session)
        s = await sessions.get_by_token_hash(stale_hash)
        await sessions.touch(
            s.id, datetime.now(timezone.utc) - timedelta(hours=2), datetime.now(timezone.utc) - timedelta(hours=1)
        )
        await session.commit()

    # Un login cualquiera poda las sesiones muertas de todos los usuarios.
    await service.login("ealfaro", "correcto-y-largo", None, None)
    async with session_factory() as session:
        assert await SqlAuthSessionRepository(session).get_by_token_hash(stale_hash) is None


# ── Dependencias de la API (modo abierto/protegido) ─────────────────────────


def _fake_request(service: AuthService):
    from types import SimpleNamespace

    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth=service)))


async def test_require_admin_open_mode_lets_everyone_pass(session_factory):
    """En modo abierto un usuario logueado no-admin no puede tener menos
    permisos que un anónimo (antes recibía un 403 saltable cerrando sesión)."""
    from noc.adapters.api.deps import require_admin

    service = make_service(session_factory)
    admin = await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    peon = await service.create_user("peon", "Peón", "correcto-y-largo", is_admin=False)
    await service.set_enabled(admin.id, False)  # válvula: modo abierto de nuevo
    assert await service.is_protected_mode() is False

    peon_user = await service.get_user(peon.id)
    assert await require_admin(_fake_request(service), peon_user) is peon_user
    assert await require_admin(_fake_request(service), None) is None


async def test_require_admin_protected_mode_rejects_non_admin(session_factory):
    from fastapi import HTTPException

    from noc.adapters.api.deps import require_admin

    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    peon = await service.create_user("peon", "Peón", "correcto-y-largo", is_admin=False)
    assert await service.is_protected_mode() is True

    peon_user = await service.get_user(peon.id)
    with pytest.raises(HTTPException) as exc:
        await require_admin(_fake_request(service), peon_user)
    assert exc.value.status_code == 403


async def test_login_log_requires_session_even_in_open_mode(session_factory):
    from fastapi import HTTPException

    from noc.adapters.api.routers.auth import login_log

    service = make_service(session_factory)
    with pytest.raises(HTTPException) as exc:
        await login_log(_fake_request(service), None, limit=100, before_id=None)
    assert exc.value.status_code == 401


# ── Gestión de usuarios ──────────────────────────────────────────────────────


async def test_create_user_rejects_duplicate_username(session_factory):
    service = make_service(session_factory)
    await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)
    with pytest.raises(AuthError) as exc:
        await service.create_user("ealfaro", "Otro Nombre", "otra-contrasena-larga", is_admin=False)
    assert exc.value.reason == "username_taken"


async def test_create_user_rejects_weak_password(session_factory):
    service = make_service(session_factory, password_min_length=10)
    with pytest.raises(AuthError) as exc:
        await service.create_user("ealfaro", "Emilio Alfaro", "corta", is_admin=True)
    assert exc.value.reason == "weak_password"


async def test_delete_user_nulls_actor_id_on_admin_operations(session_factory):
    service = make_service(session_factory)
    user = await service.create_user("ealfaro", "Emilio Alfaro", "correcto-y-largo", is_admin=True)

    async with session_factory() as session:
        op = await SqlAdminOperationRepository(session).create(
            AdminOperation(
                target_node_id="!aaaaaaaa",
                gateway_id="gw-1",
                operation_type="nodeinfo.get",
                actor_type="user",
                actor_id=user.id,
                actor_username=user.username,
                actor_display_name=user.display_name,
            )
        )
        await session.commit()
        op_id = op.id

    assert await service.delete_user(user.id) is True

    async with session_factory() as session:
        reloaded = await SqlAdminOperationRepository(session).get(op_id)
        assert reloaded is not None
        assert reloaded.actor_id is None
        # Autoría congelada: sigue siendo legible pese a que el usuario ya no existe.
        assert reloaded.actor_username == "ealfaro"
        assert reloaded.actor_display_name == "Emilio Alfaro"


# ── resolve_actor_label (CAMBIO 2/CAMBIO 9): resolver único ─────────────────


def test_resolve_actor_label_prefers_display_name():
    assert resolve_actor_label("user", "Emilio Alfaro", "admin") == "Emilio Alfaro"


def test_resolve_actor_label_falls_back_to_legacy_created_by():
    assert resolve_actor_label("system", None, "admin") == "admin"


def test_resolve_actor_label_generic_fallback():
    assert resolve_actor_label("system", None, None) == "Sistema"
    assert resolve_actor_label("api", None, None) == "API"


def test_actor_context_for_none_user_is_system():
    ctx = ActorContext.for_user(None)
    assert ctx.actor_type == "system"
    assert ctx.actor_display_name is None
