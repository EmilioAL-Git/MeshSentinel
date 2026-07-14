"""Implementación SQLAlchemy de los puertos de persistencia.

Las series temporales (posiciones/telemetría) son append-only; los "últimos
valores" se resuelven con funciones de ventana, soportadas por PostgreSQL y
SQLite >= 3.25 (ADR 0004).
"""

from dataclasses import fields
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from noc.adapters.persistence.models import (
    GatewayModel,
    GroupMemberModel,
    NeighborModel,
    NodeGatewayLinkModel,
    NodeModel,
    NodeTagModel,
    PositionModel,
    TagModel,
    TelemetryModel,
)
from noc.domain.nodes.entities import (
    GatewayInfo,
    Node,
    NodeGatewayLink,
    NodeNeighbor,
    NodeSummary,
    Position,
    Tag,
    Telemetry,
)

T = TypeVar("T")

# Campos de identidad de Node actualizables desde un avistamiento (node.seen):
# propiedades del nodo en sí, no de la pasarela que lo oyó.
_NODE_SIGHTING_FIELDS = (
    "node_num",
    "short_name",
    "long_name",
    "hw_model",
    "firmware_version",
    "role",
    "public_key",
)
# `gateway_id`/`rssi`/`snr`/`hops_away`/`via_mqtt` ya NO se copian directo del
# avistamiento: dependen de qué pasarela oyó al nodo, se derivan de
# `node_gateway_links` vía `SqlNodeRepository.apply_gateway_cache` (ver
# `IngestService._on_node_seen`, M6.1).


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

    async def apply_gateway_cache(
        self,
        node_id: str,
        gateway_id: str,
        rssi: int | None,
        snr: float | None,
        hops_away: int | None,
        via_mqtt: bool,
    ) -> None:
        """Escribe en `nodes` la caché derivada de la pasarela primaria (M6.1).

        Requiere que el nodo ya exista (llamar siempre después de
        `upsert_from_sighting`/`touch_last_seen` en la misma transacción).
        No es la fuente de verdad: solo refleja lo que `node_gateway_links` +
        `select_primary_link` ya decidieron.
        """
        existing = await self._session.get(NodeModel, node_id)
        if existing is None:
            return
        existing.gateway_id = gateway_id
        existing.rssi = rssi
        existing.snr = snr
        existing.hops_away = hops_away
        existing.via_mqtt = via_mqtt
        await self._session.flush()

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

    async def set_flag(self, node_id: str, flag: str, value: bool) -> Node | None:
        assert flag in ("is_favorite", "is_ignored")
        model = await self._session.get(NodeModel, node_id)
        if model is None:
            return None
        setattr(model, flag, value)
        await self._session.flush()
        return _node_entity(model)

    async def list_all(self) -> list[Node]:
        rows = await self._session.scalars(select(NodeModel))
        return [_node_entity(r) for r in rows]

    async def list_for_ids(self, node_ids: list[str]) -> list[Node]:
        if not node_ids:
            return []
        rows = await self._session.scalars(select(NodeModel).where(NodeModel.id.in_(node_ids)))
        return [_node_entity(r) for r in rows]

    async def set_preferred_gateway(self, node_id: str, gateway_id: str | None) -> Node | None:
        """Nivel 2 de la selección inteligente de gateway (Inspector)."""
        model = await self._session.get(NodeModel, node_id)
        if model is None:
            return None
        model.preferred_gateway_id = gateway_id
        await self._session.flush()
        return _node_entity(model)

    async def set_node_type_override(self, node_id: str, node_type: str | None) -> Node | None:
        """Clasificación manual (Inspector, Organización): None = "Automático"."""
        model = await self._session.get(NodeModel, node_id)
        if model is None:
            return None
        model.node_type_override = node_type
        await self._session.flush()
        return _node_entity(model)

    async def set_node_type_override_bulk(self, node_ids: list[str], node_type: str | None) -> int:
        """Igual que set_node_type_override pero para selección múltiple (Flota)."""
        if not node_ids:
            return 0
        result = await self._session.execute(
            update(NodeModel)
            .where(NodeModel.id.in_(node_ids))
            .values(node_type_override=node_type)
        )
        await self._session.flush()
        return result.rowcount or 0

    async def list_summaries(self) -> list[NodeSummary]:
        nodes = (
            await self._session.scalars(
                select(NodeModel).order_by(NodeModel.last_seen_at.desc(), NodeModel.id)
            )
        ).all()

        latest_pos = {p.node_id: p for p in await self._latest_per_node(PositionModel)}
        latest_tel = {
            t.node_id: t
            for t in await self._latest_per_node(TelemetryModel, TelemetryModel.kind == "device")
        }

        tags_by_node: dict[str, list[Tag]] = {}
        tag_rows = await self._session.execute(
            select(NodeTagModel.node_id, TagModel).join(TagModel, TagModel.id == NodeTagModel.tag_id)
        )
        for node_id, tag in tag_rows:
            tags_by_node.setdefault(node_id, []).append(Tag(id=tag.id, name=tag.name, color=tag.color))

        groups_by_node: dict[str, list[int]] = {}
        member_rows = await self._session.execute(select(GroupMemberModel.node_id, GroupMemberModel.group_id))
        for node_id, group_id in member_rows:
            groups_by_node.setdefault(node_id, []).append(group_id)

        return [
            NodeSummary(
                node=_node_entity(n),
                last_position=_to_entity(latest_pos[n.id], Position) if n.id in latest_pos else None,
                last_device_telemetry=_to_entity(latest_tel[n.id], Telemetry) if n.id in latest_tel else None,
                tags=tags_by_node.get(n.id, []),
                group_ids=groups_by_node.get(n.id, []),
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

    async def count_since(self, since: datetime) -> int:
        result = await self._session.scalar(
            select(func.count()).select_from(PositionModel).where(PositionModel.received_at >= since)
        )
        return int(result or 0)


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

    async def latest_by_kind(self, node_id: str) -> dict[str, Telemetry]:
        """Último registro conocido de cada kind (telemetría unificada,
        Actividad 2.0 Fase 1): el estado actual del nodo, no un paquete."""
        out: dict[str, Telemetry] = {}
        for kind in ("device", "environment", "power"):
            rows = await self.list_for_node(node_id, 1, kind)
            if rows:
                out[kind] = rows[0]
        return out

    async def count_since(self, since: datetime) -> int:
        result = await self._session.scalar(
            select(func.count()).select_from(TelemetryModel).where(TelemetryModel.received_at >= since)
        )
        return int(result or 0)


class SqlNeighborRepository:
    """Enlaces nodo<->nodo reales (NEIGHBORINFO_APP), append-only.

    Paralelo exacto a `SqlPositionRepository`: "lo último" por par
    (node_id, neighbor_id) se resuelve con row_number(), nunca se pisa.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, neighbor: NodeNeighbor) -> None:
        self._session.add(
            NeighborModel(**{f.name: getattr(neighbor, f.name) for f in fields(NodeNeighbor)})
        )
        await self._session.flush()

    async def list_for_node(self, node_id: str, limit: int) -> list[NodeNeighbor]:
        rows = await self._session.scalars(
            select(NeighborModel)
            .where(NeighborModel.node_id == node_id)
            .order_by(NeighborModel.received_at.desc())
            .limit(limit)
        )
        return [_to_entity(r, NodeNeighbor) for r in rows]

    async def list_latest_for_node(self, node_id: str) -> list[NodeNeighbor]:
        """Último enlace conocido por cada vecino de UN nodo (diseño §2:
        estado actual de su vecindario, nunca el histórico con duplicados)."""
        return await self._latest_per_pair(NeighborModel.node_id == node_id)

    async def list_latest_network(self, since: datetime | None = None) -> list[NodeNeighbor]:
        """Último enlace conocido por cada par (node_id, neighbor_id), red
        completa — para pintar la capa de topología del mapa sin N peticiones.
        `since` acota a pares oídos desde esa fecha: sin él, un par visto una
        sola vez se devolvería para siempre."""
        criteria: list[Any] = []
        if since is not None:
            criteria.append(NeighborModel.received_at >= since)
        return await self._latest_per_pair(*criteria)

    async def _latest_per_pair(self, *criteria: Any) -> list[NodeNeighbor]:
        rn = (
            func.row_number()
            .over(
                partition_by=(NeighborModel.node_id, NeighborModel.neighbor_id),
                order_by=(NeighborModel.received_at.desc(), NeighborModel.id.desc()),
            )
            .label("rn")
        )
        subq = select(NeighborModel, rn).where(*criteria).subquery()
        latest = select(subq).where(subq.c.rn == 1).subquery()
        alias = aliased(NeighborModel, latest)
        rows = (await self._session.scalars(select(alias))).all()
        return [_to_entity(r, NodeNeighbor) for r in rows]


class SqlNodeGatewayLinkRepository:
    """N:M nodo<->pasarela (M6.1): estado actual por par, no histórico."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, link: NodeGatewayLink) -> NodeGatewayLink:
        existing = await self._session.get(NodeGatewayLinkModel, (link.node_id, link.gateway_id))
        if existing is None:
            existing = NodeGatewayLinkModel(
                node_id=link.node_id,
                gateway_id=link.gateway_id,
                first_heard_at=link.first_heard_at or link.last_heard_at,
            )
            self._session.add(existing)
        for field in ("rssi", "snr", "hops_away", "via_mqtt"):
            value = getattr(link, field)
            if value is not None:
                setattr(existing, field, value)
        existing.last_heard_at = link.last_heard_at
        await self._session.flush()
        return _to_entity(existing, NodeGatewayLink)

    async def list_for_node(self, node_id: str) -> list[NodeGatewayLink]:
        rows = await self._session.scalars(
            select(NodeGatewayLinkModel)
            .where(NodeGatewayLinkModel.node_id == node_id)
            .order_by(NodeGatewayLinkModel.last_heard_at.desc())
        )
        return [_to_entity(r, NodeGatewayLink) for r in rows]

    async def list_for_nodes(self, node_ids: list[str]) -> dict[str, list[NodeGatewayLink]]:
        """Enlaces de varios nodos en una sola consulta (M6.2: enrutado de
        lotes y listado de nodos sin N+1)."""
        if not node_ids:
            return {}
        rows = await self._session.scalars(
            select(NodeGatewayLinkModel)
            .where(NodeGatewayLinkModel.node_id.in_(node_ids))
            .order_by(NodeGatewayLinkModel.last_heard_at.desc())
        )
        out: dict[str, list[NodeGatewayLink]] = {}
        for r in rows:
            out.setdefault(r.node_id, []).append(_to_entity(r, NodeGatewayLink))
        return out

    async def list_all(self) -> list[NodeGatewayLink]:
        rows = await self._session.scalars(
            select(NodeGatewayLinkModel).order_by(NodeGatewayLinkModel.last_heard_at.desc())
        )
        return [_to_entity(r, NodeGatewayLink) for r in rows]


class SqlGatewayRepository:
    """Runtime (heartbeat) y configuración (M5, ADR 0021) conviven en la misma
    fila pero se escriben por caminos distintos: `upsert()` (heartbeat) nunca
    toca las columnas de configuración; `configure()`/`update_config()`/
    `soft_delete()`/`set_desired_status()` (API de gestión) nunca tocan las de
    estado runtime salvo `managed`/`desired_status`/`deleted_at`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, info: GatewayInfo) -> GatewayInfo:
        existing = await self._session.get(GatewayModel, info.gateway_id)
        if existing is None:
            existing = GatewayModel(id=info.gateway_id)
            self._session.add(existing)
        previous_status = existing.status if existing.status else None
        existing.status = info.status
        existing.transport = info.transport
        existing.local_node_id = info.local_node_id
        existing.detail = info.detail
        existing.updated_at = info.updated_at
        existing.local_short_name = info.local_short_name
        existing.local_long_name = info.local_long_name
        existing.local_hw_model = info.local_hw_model
        existing.local_firmware_version = info.local_firmware_version
        # Historial mínimo derivado de la transición (ADR 0021 §2): no una
        # tabla de eventos, solo el último dato de cada tipo.
        if info.status == "connected" and previous_status != "connected":
            existing.last_connected_at = info.updated_at
        if info.status in ("disconnected", "unassigned") and previous_status not in (
            "disconnected",
            "unassigned",
            None,
        ):
            existing.last_disconnected_at = info.updated_at
        if info.status == "error":
            existing.last_error = info.detail
            existing.last_error_at = info.updated_at
        await self._session.flush()
        return _to_entity(existing, GatewayInfo, {"gateway_id": "id"})

    async def list_all(self, include_deleted: bool = False) -> list[GatewayInfo]:
        stmt = select(GatewayModel)
        if not include_deleted:
            stmt = stmt.where(GatewayModel.deleted_at.is_(None))
        rows = await self._session.scalars(stmt)
        return [_to_entity(r, GatewayInfo, {"gateway_id": "id"}) for r in rows]

    async def get(self, gateway_id: str) -> GatewayInfo | None:
        row = await self._session.get(GatewayModel, gateway_id)
        return _to_entity(row, GatewayInfo, {"gateway_id": "id"}) if row else None

    async def configure(
        self,
        gateway_id: str,
        name: str,
        transport_type: str,
        connection_params: dict[str, Any],
        enabled: bool,
        priority: int,
        desired_status: str,
    ) -> GatewayInfo:
        row = await self._session.get(GatewayModel, gateway_id)
        if row is None:
            row = GatewayModel(
                id=gateway_id,
                status="unassigned",
                transport=transport_type,
                updated_at=datetime.now(timezone.utc),
            )
            self._session.add(row)
        row.name = name
        row.managed = True
        row.transport_type = transport_type
        row.connection_params = connection_params
        row.enabled = enabled
        row.priority = priority
        row.desired_status = desired_status
        row.deleted_at = None
        await self._session.flush()
        return _to_entity(row, GatewayInfo, {"gateway_id": "id"})

    async def update_config(
        self,
        gateway_id: str,
        name: str | None = None,
        transport_type: str | None = None,
        connection_params: dict[str, Any] | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
        desired_status: str | None = None,
    ) -> GatewayInfo | None:
        row = await self._session.get(GatewayModel, gateway_id)
        if row is None or not row.managed:
            return None
        if name is not None:
            row.name = name
        if transport_type is not None:
            row.transport_type = transport_type
        if connection_params is not None:
            row.connection_params = connection_params
        if enabled is not None:
            row.enabled = enabled
        if priority is not None:
            row.priority = priority
        if desired_status is not None:
            row.desired_status = desired_status
        await self._session.flush()
        return _to_entity(row, GatewayInfo, {"gateway_id": "id"})

    async def set_desired_status(self, gateway_id: str, desired_status: str) -> GatewayInfo | None:
        row = await self._session.get(GatewayModel, gateway_id)
        if row is None or not row.managed:
            return None
        row.desired_status = desired_status
        await self._session.flush()
        return _to_entity(row, GatewayInfo, {"gateway_id": "id"})

    async def soft_delete(self, gateway_id: str, deleted_at: datetime) -> bool:
        row = await self._session.get(GatewayModel, gateway_id)
        if row is None or not row.managed:
            return False
        row.enabled = False
        row.desired_status = "disconnected"
        row.deleted_at = deleted_at
        await self._session.flush()
        return True
