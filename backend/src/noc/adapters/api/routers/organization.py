from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fastapi import Request

from noc.adapters.api.deps import CurrentUserDep, RequireManagerDep, RequireUserDep, SessionDep
from noc.domain.auth.entities import AuthUser
from noc.adapters.api.schemas import PreferredGatewayIn, TagOut
from noc.adapters.persistence.organization_repositories import SqlGroupRepository, SqlTagRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.domain.nodes.entities import Group, Tag

router = APIRouter(tags=["organization"])


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    is_critical: bool = False


class GroupOut(BaseModel):
    id: int
    name: str
    kind: str
    is_critical: bool
    member_count: int
    preferred_gateway_id: str | None = None
    is_personal: bool = False

    @classmethod
    def from_entity(cls, g: Group) -> "GroupOut":
        return cls(
            id=g.id or 0,
            # Solo su dueño lo ve: nombre fijo de cara al usuario (el interno lleva el username).
            name="Grupo del usuario" if g.owner_user_id is not None else g.name,
            kind=g.kind, is_critical=g.is_critical,
            member_count=g.member_count, preferred_gateway_id=g.preferred_gateway_id,
            is_personal=g.owner_user_id is not None,
        )


class GroupDetailOut(GroupOut):
    members: list[str]


class MemberIn(BaseModel):
    node_id: str = Field(pattern=r"^![0-9a-f]{8}$")


class BulkMembersIn(BaseModel):
    node_ids: list[str] = Field(min_length=1)


class BulkMembersOut(BaseModel):
    added: int
    already_member: int


class BulkRemoveOut(BaseModel):
    removed: int
    not_member: int


# ── Etiquetas ────────────────────────────────────────────────────────────────


@router.get("/tags", response_model=list[TagOut])
async def list_tags(session: SessionDep) -> list[TagOut]:
    return [TagOut.from_entity(t) for t in await SqlTagRepository(session).list_all()]


@router.post("/tags", response_model=TagOut, status_code=201)
async def create_tag(body: TagIn, session: SessionDep, _user: RequireManagerDep) -> TagOut:
    repo = SqlTagRepository(session)
    if await repo.get_by_name(body.name) is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")
    tag = await repo.create(Tag(name=body.name, color=body.color))
    await session.commit()
    return TagOut.from_entity(tag)


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, session: SessionDep, _user: RequireManagerDep) -> None:
    deleted = await SqlTagRepository(session).delete(tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
    await session.commit()


# Etiquetado masivo desde Flota. Rutas de 3 segmentos fijos: no chocan con
# DELETE /tags/{tag_id}.
@router.post("/tags/{tag_id}/nodes/bulk", response_model=BulkMembersOut)
async def add_tag_bulk(
    tag_id: int, body: BulkMembersIn, session: SessionDep, _user: RequireManagerDep
) -> BulkMembersOut:
    repo = SqlTagRepository(session)
    if not await repo.exists(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    added, already = await repo.add_tag_bulk(tag_id, body.node_ids)
    await session.commit()
    return BulkMembersOut(added=added, already_member=already)


@router.post("/tags/{tag_id}/nodes/bulk-remove", response_model=BulkRemoveOut)
async def remove_tag_bulk(
    tag_id: int, body: BulkMembersIn, session: SessionDep, _user: RequireManagerDep
) -> BulkRemoveOut:
    repo = SqlTagRepository(session)
    if not await repo.exists(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    removed, not_tagged = await repo.remove_tag_bulk(tag_id, body.node_ids)
    await session.commit()
    return BulkRemoveOut(removed=removed, not_member=not_tagged)


# ── Grupos ───────────────────────────────────────────────────────────────────


async def _visible_group(repo: SqlGroupRepository, group_id: int, user: AuthUser | None) -> Group:
    """Grupo accesible para `user`: un grupo personal ajeno responde 404 (no
    se revela que existe), igual que si no existiera (ADR 0029)."""
    group = await repo.get(group_id)
    if group is None or (
        group.owner_user_id is not None and (user is None or group.owner_user_id != user.id)
    ):
        raise HTTPException(status_code=404, detail="Group not found")
    return group


async def _group_writer(request: Request, repo: SqlGroupRepository, group_id: int, user: AuthUser | None) -> Group:
    """Edición de miembros: grupo personal = SOLO su dueño (ni admin); grupo
    compartido = gestor o admin (en modo abierto, cualquiera)."""
    group = await _visible_group(repo, group_id, user)
    if group.owner_user_id is not None:
        return group
    if await request.app.state.auth.is_protected_mode() and (user is None or not user.can_manage):
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(status_code=403, detail="Requiere rol de gestor o administrador")
    return group


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(session: SessionDep, current_user: CurrentUserDep) -> list[GroupOut]:
    viewer = current_user.id if current_user else None
    return [GroupOut.from_entity(g) for g in await SqlGroupRepository(session).list_with_counts(viewer)]


@router.get("/groups/mine", response_model=GroupOut | None)
async def get_my_group(session: SessionDep, user: RequireUserDep) -> GroupOut | None:
    """El Grupo del usuario, o null si aún no lo ha creado. Registrada ANTES
    de /groups/{group_id}."""
    g = await SqlGroupRepository(session).get_personal(user.id or 0)
    return GroupOut.from_entity(g) if g else None


@router.post("/groups/mine", response_model=GroupOut)
async def ensure_my_group(session: SessionDep, user: RequireUserDep) -> GroupOut:
    """Crea (idempotente) el grupo personal del usuario. Uno por cuenta."""
    repo = SqlGroupRepository(session)
    g = await repo.get_personal(user.id or 0)
    if g is None:
        g = await repo.create_personal(user.id or 0, user.username)
        await session.commit()
    return GroupOut.from_entity(g)


@router.post("/groups", response_model=GroupOut, status_code=201)
async def create_group(body: GroupIn, session: SessionDep, _user: RequireManagerDep) -> GroupOut:
    group = await SqlGroupRepository(session).create(Group(name=body.name, is_critical=body.is_critical))
    await session.commit()
    return GroupOut.from_entity(group)


@router.get("/groups/{group_id}", response_model=GroupDetailOut)
async def get_group(group_id: int, session: SessionDep, current_user: CurrentUserDep) -> GroupDetailOut:
    repo = SqlGroupRepository(session)
    group = await _visible_group(repo, group_id, current_user)
    members = await repo.members(group_id)
    return GroupDetailOut(**GroupOut.from_entity(group).model_dump(), members=members)


@router.put("/groups/{group_id}/preferred-gateway", response_model=GroupOut)
async def set_group_preferred_gateway(
    group_id: int, body: PreferredGatewayIn, session: SessionDep, _user: RequireManagerDep
) -> GroupOut:
    """Nivel 3 de la selección inteligente de gateway (editor de grupo)."""
    if (g := await SqlGroupRepository(session).get(group_id)) is not None and g.owner_user_id is not None:
        raise HTTPException(status_code=400, detail="El grupo del usuario no admite pasarela preferida")
    group = await SqlGroupRepository(session).set_preferred_gateway(group_id, body.gateway_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    await session.commit()
    return GroupOut.from_entity(group)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: int, session: SessionDep, _user: RequireManagerDep) -> None:
    if (g := await SqlGroupRepository(session).get(group_id)) is not None and g.owner_user_id is not None:
        raise HTTPException(status_code=400, detail="El grupo del usuario no se puede eliminar")
    deleted = await SqlGroupRepository(session).delete(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    await session.commit()


# Gestión masiva desde Flota: registradas ANTES de /members/{node_id} —
# igual que /gateways/stats antes de /gateways/{gateway_id}. Starlette hace
# *partial match* de ruta antes que de método: sin este orden, un POST a
# .../members/bulk encaja primero con el DELETE .../members/{node_id}
# (node_id="bulk") y responde 405 en vez de llegar a esta ruta.
@router.post("/groups/{group_id}/members/bulk", response_model=BulkMembersOut)
async def add_group_members_bulk(
    group_id: int, body: BulkMembersIn, session: SessionDep, request: Request, current_user: CurrentUserDep
) -> BulkMembersOut:
    repo = SqlGroupRepository(session)
    await _group_writer(request, repo, group_id, current_user)
    added, already = await repo.add_members_bulk(group_id, body.node_ids)
    await session.commit()
    return BulkMembersOut(added=added, already_member=already)


@router.post("/groups/{group_id}/members/bulk-remove", response_model=BulkRemoveOut)
async def remove_group_members_bulk(
    group_id: int, body: BulkMembersIn, session: SessionDep, request: Request, current_user: CurrentUserDep
) -> BulkRemoveOut:
    repo = SqlGroupRepository(session)
    await _group_writer(request, repo, group_id, current_user)
    removed, not_member = await repo.remove_members_bulk(group_id, body.node_ids)
    await session.commit()
    return BulkRemoveOut(removed=removed, not_member=not_member)


@router.post("/groups/{group_id}/members", status_code=204)
async def add_group_member(group_id: int, body: MemberIn, session: SessionDep, request: Request, current_user: CurrentUserDep) -> None:
    repo = SqlGroupRepository(session)
    await _group_writer(request, repo, group_id, current_user)
    if await SqlNodeRepository(session).get(body.node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await repo.add_member(group_id, body.node_id)
    await session.commit()


@router.delete("/groups/{group_id}/members/{node_id}", status_code=204)
async def remove_group_member(group_id: int, node_id: str, session: SessionDep, request: Request, current_user: CurrentUserDep) -> None:
    await _group_writer(request, SqlGroupRepository(session), group_id, current_user)
    removed = await SqlGroupRepository(session).remove_member(group_id, node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Membership not found")
    await session.commit()
