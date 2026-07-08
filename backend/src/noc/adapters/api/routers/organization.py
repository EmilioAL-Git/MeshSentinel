from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.schemas import TagOut
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

    @classmethod
    def from_entity(cls, g: Group) -> "GroupOut":
        return cls(id=g.id or 0, name=g.name, kind=g.kind, is_critical=g.is_critical, member_count=g.member_count)


class GroupDetailOut(GroupOut):
    members: list[str]


class MemberIn(BaseModel):
    node_id: str = Field(pattern=r"^![0-9a-f]{8}$")


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


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: int, session: SessionDep) -> None:
    deleted = await SqlGroupRepository(session).delete(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    await session.commit()


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
