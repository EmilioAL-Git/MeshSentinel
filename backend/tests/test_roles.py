"""Roles y datos personales (ADR 0029): permisos, favoritos y grupo del usuario."""

import pytest

from noc.adapters.persistence.organization_repositories import SqlGroupRepository, SqlUserFavoriteRepository
from noc.application.auth.service import AuthError
from noc.domain.nodes.entities import Group
from test_auth import make_service
from test_organization import NODES, seed


async def _users(session_factory):
    service = make_service(session_factory)
    admin = await service.create_user("root", "Root", "correcto-y-largo", role="admin")
    manager = await service.create_user("gestor", "Gestor", "correcto-y-largo", role="manager")
    user = await service.create_user("peon", "Peón", "correcto-y-largo", role="user")
    return service, admin, manager, user


async def test_roles_and_permissions(session_factory):
    service, admin, manager, user = await _users(session_factory)
    assert (admin.role, manager.role, user.role) == ("admin", "manager", "user")
    assert admin.is_admin and not manager.is_admin and not user.is_admin
    assert admin.can_manage and manager.can_manage and not user.can_manage
    with pytest.raises(AuthError):
        await service.create_user("x", "X", "correcto-y-largo", role="superman")
    changed = await service.set_role(user.id, "manager")
    assert changed.role == "manager" and changed.can_manage
    # legacy: set_admin sigue funcionando
    assert (await service.set_admin(user.id, True)).role == "admin"


async def test_personal_favorites_are_per_user(session_factory):
    await seed(session_factory)
    service, _admin, manager, user = await _users(session_factory)
    async with session_factory() as s:
        repo = SqlUserFavoriteRepository(s)
        assert await repo.set_bulk(manager.id, [NODES[0], NODES[1], "!ffffffff"], True) == (2, 1)
        assert await repo.set_bulk(user.id, [NODES[0]], True) == (1, 0)
        assert await repo.set_bulk(user.id, [NODES[0]], True) == (0, 1)
        await s.commit()
    async with session_factory() as s:
        repo = SqlUserFavoriteRepository(s)
        assert await repo.ids_for_user(manager.id) == {NODES[0], NODES[1]}
        assert await repo.ids_for_user(user.id) == {NODES[0]}
        assert await repo.set_bulk(user.id, [NODES[0]], False) == (1, 0)
        await s.commit()
        assert await repo.ids_for_user(manager.id) == {NODES[0], NODES[1]}


async def test_personal_group_is_private_and_unique(session_factory):
    await seed(session_factory)
    service, _admin, manager, user = await _users(session_factory)
    async with session_factory() as s:
        repo = SqlGroupRepository(s)
        shared = await repo.create(Group(name="Albacete"))
        mine = await repo.create_personal(user.id, user.username)
        theirs = await repo.create_personal(manager.id, manager.username)
        await repo.add_member(mine.id, NODES[0])
        await s.commit()
        assert mine.owner_user_id == user.id and mine.name != theirs.name
        assert {g.id for g in await repo.list_with_counts(None)} == {shared.id}
        assert {g.id for g in await repo.list_with_counts(user.id)} == {shared.id, mine.id}
        assert {g.id for g in await repo.list_with_counts(manager.id)} == {shared.id, theirs.id}
        assert (await repo.get_personal(user.id)).member_count == 1
    # borrar el usuario limpia favoritos y grupo personal
    await service.delete_user(user.id)
    async with session_factory() as s:
        assert await SqlGroupRepository(s).get_personal(user.id) is None
