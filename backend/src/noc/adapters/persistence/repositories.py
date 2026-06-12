"""Implementación SQLAlchemy de los puertos de persistencia.

Las series temporales (posiciones/telemetría) son append-only; los "últimos
valores" se resuelven con funciones de ventana, soportadas por PostgreSQL y
SQLite >= 3.25 (ADR 0004).
"""

from dataclasses import fields
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from noc.adapters.persistence.models import GatewayModel, NodeModel, PositionModel, TelemetryModel
from noc.domain.nodes.entities import GatewayInfo, Node, NodeSummary, Position, Telemetry

T = TypeVar("T")

# Campos de Node actualizables desde un avistamiento (node.seen)
_NODE_SIGHTING_FIELDS = (
    "node_num",
    "short_name",
    "long_name",
    "hw_model",
    "firmware_version",
    "role",
    "snr",
    "rssi",
    "hops_away",
    "via_mqtt",
    "public_key",
    "gateway_id",
)


def _to_entity(model: Any, entity_cls: type[T], mapping: dict[str, str] | None = None) -> T:
    mapping = mapping or {}
    kwargs = {}
    for f in fields(entity_cls):  # type: ignore[arg-type]
        attr = mapping.get(f.name, f.name)
        kwargs[f.name] = getattr(model, attr)
    return entity_cls(**kwargs)


def _node_entity(m: NodeModel) -> Node:
    return _to_entity(m, Node, {"node_id": "id"})


class SqlNodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_from_sighting(self, node: Node, seen_at: datetime) -> Node:
        existing = await self._session.get(NodeModel, node.node_id)
        if existing is None:
            existing = NodeModel(id=node.node_id, first_seen_at=seen_at, last_seen_at=seen_at)
            self._session.add(existing)
        for field in _NODE_SIGHTING_FIELDS:
            value = getattr(node, field)
            if value is not None:
                setattr(existing, field, value)
        existing.last_seen_at = seen_at
        await self._session.flush()
        return _node_entity(existing)

    async def touch_last_seen(self, node_id: str, gateway_id: str | None, seen_at: datetime) -> None:
        existing = await self._session.get(NodeModel, node_id)
        if existing is None:
            # Primera noticia del nodo por telemetría/posición antes que NodeInfo
            existing = NodeModel(
                id=node_id, gateway_id=gateway_id, first_seen_at=seen_at, last_seen_at=seen_at
            )
            self._session.add(existing)
        else:
            existing.last_seen_at = seen_at
        await self._session.flush()

    async def get(self, node_id: str) -> Node | None:
        model = await self._session.get(NodeModel, node_id)
        return _node_entity(model) if model else None

    async def list_summaries(self) -> list[NodeSummary]:
        nodes = (await self._session.scalars(select(NodeModel).order_by(NodeModel.last_seen_at.desc()))).all()

        latest_pos = {p.node_id: p for p in await self._latest_per_node(PositionModel)}
        latest_tel = {
            t.node_id: t
            for t in await self._latest_per_node(TelemetryModel, TelemetryModel.kind == "device")
        }
        return [
            NodeSummary(
                node=_node_entity(n),
                last_position=_to_entity(latest_pos[n.id], Position) if n.id in latest_pos else None,
                last_device_telemetry=_to_entity(latest_tel[n.id], Telemetry) if n.id in latest_tel else None,
            )
            for n in nodes
        ]

    async def _latest_per_node(self, model: type, *criteria: Any) -> list[Any]:
        rn = (
            func.row_number()
            .over(partition_by=model.node_id, order_by=(model.received_at.desc(), model.id.desc()))
            .label("rn")
        )
        subq = select(model, rn).where(*criteria).subquery()
        latest = select(subq).where(subq.c.rn == 1).subquery()
        alias = aliased(model, latest)
        return list((await self._session.scalars(select(alias))).all())


class SqlPositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, position: Position) -> None:
        self._session.add(
            PositionModel(**{f.name: getattr(position, f.name) for f in fields(Position)})
        )
        await self._session.flush()

    async def list_for_node(self, node_id: str, limit: int) -> list[Position]:
        rows = await self._session.scalars(
            select(PositionModel)
            .where(PositionModel.node_id == node_id)
            .order_by(PositionModel.received_at.desc())
            .limit(limit)
        )
        return [_to_entity(r, Position) for r in rows]


class SqlTelemetryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, telemetry: Telemetry) -> None:
        self._session.add(
            TelemetryModel(**{f.name: getattr(telemetry, f.name) for f in fields(Telemetry)})
        )
        await self._session.flush()

    async def list_for_node(self, node_id: str, limit: int, kind: str | None) -> list[Telemetry]:
        stmt = select(TelemetryModel).where(TelemetryModel.node_id == node_id)
        if kind:
            stmt = stmt.where(TelemetryModel.kind == kind)
        rows = await self._session.scalars(stmt.order_by(TelemetryModel.received_at.desc()).limit(limit))
        return [_to_entity(r, Telemetry) for r in rows]


class SqlGatewayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, info: GatewayInfo) -> None:
        existing = await self._session.get(GatewayModel, info.gateway_id)
        if existing is None:
            existing = GatewayModel(id=info.gateway_id)
            self._session.add(existing)
        existing.status = info.status
        existing.transport = info.transport
        existing.local_node_id = info.local_node_id
        existing.detail = info.detail
        existing.updated_at = info.updated_at
        await self._session.flush()

    async def list_all(self) -> list[GatewayInfo]:
        rows = await self._session.scalars(select(GatewayModel))
        return [_to_entity(r, GatewayInfo, {"gateway_id": "id"}) for r in rows]
