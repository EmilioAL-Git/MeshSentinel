"""Tokens Bearer de API (ADR 0035)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from noc.adapters.api.deps import get_current_user, require_manager, require_user
from noc.adapters.persistence.models import ApiTokenModel
from noc.application.auth.service import AuthError
from test_auth import make_service


def _request(service, authorization: str | None = None, cookie: str | None = None):
    headers = {"authorization": authorization} if authorization else {}
    cookies = {"ms_session": cookie} if cookie else {}
    return SimpleNamespace(headers=headers, cookies=cookies, app=SimpleNamespace(state=SimpleNamespace(auth=service)))


async def test_token_lifecycle_and_only_hash_is_stored(session_factory):
    service = make_service(session_factory)
    token, plain = await service.create_api_token("grafana", "manager", None, "root")
    assert plain.startswith("msk_") and token.token_prefix == plain[:8]
    assert plain not in (token.token_hash, token.name)
    async with session_factory() as s:
        row = (await s.get(ApiTokenModel, token.id))
        assert row.token_hash != plain and len(row.token_hash) == 64

    principal = await service.resolve_api_token(plain)
    assert principal.username == "token:grafana" and principal.can_manage and not principal.is_admin
    assert principal.id is None
    assert await service.resolve_api_token("msk_inventado") is None
    assert await service.resolve_api_token("sin-prefijo") is None

    assert await service.revoke_api_token(token.id) is True
    assert await service.resolve_api_token(plain) is None
    assert await service.revoke_api_token(token.id) is False


async def test_admin_role_and_duplicate_names_are_rejected(session_factory):
    service = make_service(session_factory)
    with pytest.raises(AuthError):
        await service.create_api_token("x", "admin", None, None)
    await service.create_api_token("dup", "user", None, None)
    with pytest.raises(AuthError) as err:
        await service.create_api_token("dup", "user", None, None)
    assert err.value.reason == "duplicate_name"


async def test_expired_token_is_rejected(session_factory):
    service = make_service(session_factory)
    token, plain = await service.create_api_token("tmp", "user", 1, None)
    assert await service.resolve_api_token(plain) is not None
    async with session_factory() as s, s.begin():
        row = await s.get(ApiTokenModel, token.id)
        await s.execute(update(ApiTokenModel).where(ApiTokenModel.id == token.id).values(expires_at=row.created_at - timedelta(days=1)))
    assert await service.resolve_api_token(plain) is None


async def test_dependencies_bearer_valid_invalid_and_personal_space(session_factory):
    service = make_service(session_factory)
    await service.create_user("root", "Root", "correcto-y-largo", role="admin")  # activa el modo protegido
    _, manager_token = await service.create_api_token("ci", "manager", None, "root")
    _, user_token = await service.create_api_token("ro", "user", None, "root")

    me = await get_current_user(_request(service, f"Bearer {manager_token}"))
    assert me.username == "token:ci"
    # el manager-token pasa require_manager; el user-token no
    assert await require_manager(_request(service), me) is me
    ro = await get_current_user(_request(service, f"Bearer {user_token}"))
    with pytest.raises(HTTPException) as e403:
        await require_manager(_request(service), ro)
    assert e403.value.status_code == 403
    # sin espacio personal
    with pytest.raises(HTTPException) as e:
        await require_user(me)
    assert e.value.status_code == 403
    # un Bearer inválido es 401 y NO cae a la cookie
    with pytest.raises(HTTPException) as bad:
        await get_current_user(_request(service, "Bearer msk_nope", cookie="cualquiera"))
    assert bad.value.status_code == 401
    # sin cabecera ni cookie: anónimo
    assert await get_current_user(_request(service)) is None
