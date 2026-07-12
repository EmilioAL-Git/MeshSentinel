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
                member_count=int(counts.get(g.id, 0)), preferred_gateway_id=g.preferred_gateway_id,
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
        return Group(
            id=g.id, name=g.name, kind=g.kind, is_critical=g.is_critical,
            member_count=int(count or 0), preferred_gateway_id=g.preferred_gateway_id,
        )

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

    async def set_preferred_gateway(self, group_id: int, gateway_id: str | None) -> Group | None:
        """Nivel 3 de la selección inteligente de gateway (editor de grupo)."""
        m = await self._session.get(GroupModel, group_id)
        if m is None:
            return None
        m.preferred_gateway_id = gateway_id
        await self._session.flush()
        return await self.get(group_id)

    async def preferred_gateway_for_node(self, node_id: str) -> str | None:
        """Nivel 3 resuelto para UN nodo: el grupo con preferencia definida y
        menor id entre los que pertenece (desempate determinista si hay
        varios grupos con preferencias distintas — ver gateway_routing.py)."""
        return await self._session.scalar(
            select(GroupModel.preferred_gateway_id)
            .join(GroupMemberModel, GroupMemberModel.group_id == GroupModel.id)
            .where(GroupMemberModel.node_id == node_id, GroupModel.preferred_gateway_id.is_not(None))
            .order_by(GroupModel.id)
            .limit(1)
        )

    async def preferred_gateways_for_nodes(self, node_ids: list[str]) -> dict[str, str]:
        """Versión en bloque de `preferred_gateway_for_node`: una sola consulta
        para cualquier cantidad de nodos (selección inteligente de gateway
        en lotes — `gateway_routing.resolve_gateways_for_nodes`)."""
        if not node_ids:
            return {}
        rows = await self._session.execute(
            select(GroupMemberModel.node_id, GroupModel.preferred_gateway_id)
            .join(GroupModel, GroupMemberModel.group_id == GroupModel.id)
            .where(GroupMemberModel.node_id.in_(node_ids), GroupModel.preferred_gateway_id.is_not(None))
            .order_by(GroupModel.id)
        )
        result: dict[str, str] = {}
        for node_id, preferred in rows.all():
            result.setdefault(node_id, preferred)  # primer grupo (menor id) gana
        return result

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

    async def add_members_bulk(self, group_id: int, node_ids: list[str]) -> tuple[int, int]:
        """Añade en bloque (Flota → gestión masiva de grupos): una sola
        consulta para saber quién ya es miembro, un solo flush para el
        resto — nunca N idas y vueltas por nodo. Devuelve (added, already)."""
        requested = list(dict.fromkeys(node_ids))  # dedupe conservando orden
        existing = set(
            await self._session.scalars(
                select(GroupMemberModel.node_id).where(
                    GroupMemberModel.group_id == group_id,
                    GroupMemberModel.node_id.in_(requested),
                )
            )
        )
        new_ids = [n for n in requested if n not in existing]
        for node_id in new_ids:
            self._session.add(GroupMemberModel(group_id=group_id, node_id=node_id))
        if new_ids:
            await self._session.flush()
        return len(new_ids), len(requested) - len(new_ids)

    async def remove_members_bulk(self, group_id: int, node_ids: list[str]) -> tuple[int, int]:
        """Quita en bloque: un DELETE...IN, sin ida y vuelta por nodo.
        Devuelve (removed, not_member)."""
        requested = list(dict.fromkeys(node_ids))
        existing = set(
            await self._session.scalars(
                select(GroupMemberModel.node_id).where(
                    GroupMemberModel.group_id == group_id,
                    GroupMemberModel.node_id.in_(requested),
                )
            )
        )
        if existing:
            await self._session.execute(
                delete(GroupMemberModel).where(
                    GroupMemberModel.group_id == group_id,
                    GroupMemberModel.node_id.in_(existing),
                )
            )
            await self._session.flush()
        return len(existing), len(requested) - len(existing)
