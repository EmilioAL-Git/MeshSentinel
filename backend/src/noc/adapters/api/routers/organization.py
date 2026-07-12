from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
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

    @classmethod
    def from_entity(cls, g: Group) -> "GroupOut":
        return cls(
            id=g.id or 0, name=g.name, kind=g.kind, is_critical=g.is_critical,
            member_count=g.member_count, preferred_gateway_id=g.preferred_gateway_id,
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
async def create_tag(body: TagIn, session: SessionDep) -> TagOut:
    repo = SqlTagRepository(session)
    if await repo.get_by_name(body.name) is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")
    tag = await repo.create(Tag(name=body.name, color=body.color))
    await session.commit()
    return TagOut.from_entity(tag)


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, session: SessionDep) -> None:
    deleted = await SqlTagRepository(session).delete(tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
    await session.commit()


# ── Grupos ───────────────────────────────────────────────────────────────────


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(session: SessionDep) -> list[GroupOut]:
    return [GroupOut.from_entity(g) for g in await SqlGroupRepository(session).list_with_counts()]


@router.post("/groups", response_model=GroupOut, status_code=201)
async def create_group(body: GroupIn, session: SessionDep) -> GroupOut:
    group = await SqlGroupRepository(session).create(Group(name=body.name, is_critical=body.is_critical))
    await session.commit()
    return GroupOut.from_entity(group)


@router.get("/groups/{group_id}", response_model=GroupDetailOut)
async def get_group(group_id: int, session: SessionDep) -> GroupDetailOut:
    repo = SqlGroupRepository(session)
    group = await repo.get(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    members = await repo.members(group_id)
    return GroupDetailOut(**GroupOut.from_entity(group).model_dump(), members=members)


@router.put("/groups/{group_id}/preferred-gateway", response_model=GroupOut)
async def set_group_preferred_gateway(
    group_id: int, body: PreferredGatewayIn, session: SessionDep
) -> GroupOut:
    """Nivel 3 de la selección inteligente de gateway (editor de grupo)."""
    group = await SqlGroupRepository(session).set_preferred_gateway(group_id, body.gateway_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    await session.commit()
    return GroupOut.from_entity(group)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: int, session: SessionDep) -> None:
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
async def add_group_members_bulk(group_id: int, body: BulkMembersIn, session: SessionDep) -> BulkMembersOut:
    repo = SqlGroupRepository(session)
    if await repo.get(group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    added, already = await repo.add_members_bulk(group_id, body.node_ids)
    await session.commit()
    return BulkMembersOut(added=added, already_member=already)


@router.post("/groups/{group_id}/members/bulk-remove", response_model=BulkRemoveOut)
async def remove_group_members_bulk(group_id: int, body: BulkMembersIn, session: SessionDep) -> BulkRemoveOut:
    repo = SqlGroupRepository(session)
    if await repo.get(group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    removed, not_member = await repo.remove_members_bulk(group_id, body.node_ids)
    await session.commit()
    return BulkRemoveOut(removed=removed, not_member=not_member)


@router.post("/groups/{group_id}/members", status_code=204)
async def add_group_member(group_id: int, body: MemberIn, session: SessionDep) -> None:
    repo = SqlGroupRepository(session)
    if await repo.get(group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if await SqlNodeRepository(session).get(body.node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await repo.add_member(group_id, body.node_id)
    await session.commit()


@router.delete("/groups/{group_id}/members/{node_id}", status_code=204)
async def remove_group_member(group_id: int, node_id: str, session: SessionDep) -> None:
    removed = await SqlGroupRepository(session).remove_member(group_id, node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Membership not found")
    await session.commit()
