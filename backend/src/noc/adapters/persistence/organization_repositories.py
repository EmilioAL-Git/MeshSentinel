"""Persistencia de la organización de nodos (M1.2): etiquetas y grupos.

Metadatos exclusivos del NOC: nunca generan tráfico hacia la malla.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import GroupMemberModel, GroupModel, NodeTagModel, TagModel
from noc.domain.nodes.entities import Group, Tag


class SqlTagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Tag]:
        rows = await self._session.scalars(select(TagModel).order_by(TagModel.name))
        return [Tag(id=t.id, name=t.name, color=t.color) for t in rows]

    async def get_by_name(self, name: str) -> Tag | None:
        t = await self._session.scalar(select(TagModel).where(TagModel.name == name))
        return Tag(id=t.id, name=t.name, color=t.color) if t else None

    async def create(self, tag: Tag) -> Tag:
        m = TagModel(name=tag.name, color=tag.color)
        self._session.add(m)
        await self._session.flush()
        return Tag(id=m.id, name=m.name, color=m.color)

    async def delete(self, tag_id: int) -> bool:
        m = await self._session.get(TagModel, tag_id)
        if m is None:
            return False
        # Borrado explícito de la relación: SQLite no aplica ON DELETE CASCADE
        # sin PRAGMA foreign_keys y no dependemos de ello (ADR 0004)
        await self._session.execute(delete(NodeTagModel).where(NodeTagModel.tag_id == tag_id))
        await self._session.delete(m)
        await self._session.flush()
        return True

    async def set_node_tags(self, node_id: str, tag_ids: list[int]) -> None:
        """Reemplaza el conjunto de etiquetas del nodo (idempotente)."""
        await self._session.execute(delete(NodeTagModel).where(NodeTagModel.node_id == node_id))
        for tag_id in set(tag_ids):
            self._session.add(NodeTagModel(node_id=node_id, tag_id=tag_id))
        await self._session.flush()


class SqlGroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_with_counts(self) -> list[Group]:
        counts = dict(
            (
                await self._session.execute(
                    select(GroupMemberModel.group_id, func.count()).group_by(GroupMemberModel.group_id)
                )
            ).all()
        )
        rows = await self._session.scalars(select(GroupModel).order_by(GroupModel.name))
        return [
            Group(
                id=g.id, name=g.name, kind=g.kind, is_critical=g.is_critical,
                member_count=int(counts.get(g.id, 0)),
            )
            for g in rows
        ]

    async def get(self, group_id: int) -> Group | None:
        g = await self._session.get(GroupModel, group_id)
        if g is None:
            return None
        count = await self._session.scalar(
            select(func.count()).select_from(GroupMemberModel).where(GroupMemberModel.group_id == group_id)
        )
        return Group(id=g.id, name=g.name, kind=g.kind, is_critical=g.is_critical, member_count=int(count or 0))

    async def members(self, group_id: int) -> list[str]:
        rows = await self._session.scalars(
            select(GroupMemberModel.node_id).where(GroupMemberModel.group_id == group_id)
        )
        return list(rows)

    async def create(self, group: Group) -> Group:
        m = GroupModel(name=group.name, kind=group.kind, is_critical=group.is_critical)
        self._session.add(m)
        await self._session.flush()
        return Group(id=m.id, name=m.name, kind=m.kind, is_critical=m.is_critical, member_count=0)

    async def delete(self, group_id: int) -> bool:
        m = await self._session.get(GroupModel, group_id)
        if m is None:
            return False
        await self._session.execute(delete(GroupMemberModel).where(GroupMemberModel.group_id == group_id))
        await self._session.delete(m)
        await self._session.flush()
        return True

    async def add_member(self, group_id: int, node_id: str) -> None:
        exists = await self._session.get(GroupMemberModel, (group_id, node_id))
        if exists is None:
            self._session.add(GroupMemberModel(group_id=group_id, node_id=node_id))
            await self._session.flush()

    async def remove_member(self, group_id: int, node_id: str) -> bool:
        m = await self._session.get(GroupMemberModel, (group_id, node_id))
        if m is None:
            return False
        await self._session.delete(m)
        await self._session.flush()
        return True
