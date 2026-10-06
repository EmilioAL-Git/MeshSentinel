"""Fusión del historial de una identidad vieja en la nueva (ADR 0034).

Acción DESTRUCTIVA y manual: mueve todo lo que cuelga del nodo viejo al nuevo
y borra la fila vieja, en la transacción de la sesión que recibe (el llamador
hace commit). Las reglas de qué pares son fusionables viven en
`application/node_identity.py`; aquí solo se mueven filas.

Tablas con clave compuesta (tags, grupos, favoritos, enlaces con pasarela,
banderas Nexus) pueden chocar con filas ya existentes del nodo nuevo: las del
viejo que chocarían se descartan antes de mover (el nuevo manda).
No se tocan a propósito: `alerts`/`activity_log` (auditoría histórica, solo
mencionan el id viejo), `nexus_operations` (registro de lo que se envió).
"""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import (
    AdminOperationModel,
    ChatMessageModel,
    GroupMemberModel,
    NeighborModel,
    NexusNodeFlagModel,
    NodeGatewayLinkModel,
    NodeModel,
    NodeTagModel,
    PositionModel,
    TelemetryModel,
    TraceHopModel,
    TraceModel,
    UserFavoriteModel,
)


async def _move_keyed(session: AsyncSession, model: type, key_col: str, old: str, new: str) -> int:
    """Mueve filas de una tabla con PK compuesta (node_id + `key_col`),
    descartando antes las del viejo cuya clave ya existe en el nuevo."""
    node_col = model.node_id
    key_attr = getattr(model, key_col)
    existing = set(
        (await session.scalars(select(key_attr).where(node_col == new))).all()
    )
    if existing:
        await session.execute(delete(model).where(node_col == old, key_attr.in_(existing)))
    result = await session.execute(update(model).where(node_col == old).values(node_id=new))
    return result.rowcount or 0


async def merge_identity(session: AsyncSession, predecessor_id: str, successor_id: str) -> dict[str, int]:
    old = await session.get(NodeModel, predecessor_id)
    new = await session.get(NodeModel, successor_id)
    if old is None or new is None:
        raise LookupError("node not found")
    moved: dict[str, int] = {}

    async def simple(name: str, model: type, column: str) -> None:
        res = await session.execute(
            update(model).where(getattr(model, column) == predecessor_id).values({column: successor_id})
        )
        moved[name] = moved.get(name, 0) + (res.rowcount or 0)

    await simple("positions", PositionModel, "node_id")
    await simple("telemetry", TelemetryModel, "node_id")
    await simple("neighbors", NeighborModel, "node_id")
    await simple("neighbors", NeighborModel, "neighbor_id")
    await simple("chat_sent", ChatMessageModel, "from_node_id")
    await simple("chat_received", ChatMessageModel, "to_node_id")
    await simple("traces", TraceModel, "origin_id")
    await simple("traces", TraceModel, "target_id")
    await simple("trace_hops", TraceHopModel, "src_id")
    await simple("trace_hops", TraceHopModel, "dst_id")
    await simple("admin_operations", AdminOperationModel, "target_node_id")

    moved["tags"] = await _move_keyed(session, NodeTagModel, "tag_id", predecessor_id, successor_id)
    moved["groups"] = await _move_keyed(session, GroupMemberModel, "group_id", predecessor_id, successor_id)
    moved["favorites"] = await _move_keyed(session, UserFavoriteModel, "user_id", predecessor_id, successor_id)
    moved["gateway_links"] = await _move_keyed(
        session, NodeGatewayLinkModel, "gateway_id", predecessor_id, successor_id
    )

    # Banderas Nexus: como nodo que responde (node_id) y como sujeto
    existing_flags = {
        (f.flag_type, f.subject_node_id)
        for f in (await session.scalars(select(NexusNodeFlagModel).where(NexusNodeFlagModel.node_id == successor_id))).all()
    }
    for f in (await session.scalars(select(NexusNodeFlagModel).where(NexusNodeFlagModel.node_id == predecessor_id))).all():
        if (f.flag_type, f.subject_node_id) in existing_flags:
            await session.delete(f)
        else:
            f.node_id = successor_id
    await session.flush()
    for f in (await session.scalars(select(NexusNodeFlagModel).where(NexusNodeFlagModel.subject_node_id == predecessor_id))).all():
        clash = await session.scalar(
            select(NexusNodeFlagModel.id).where(
                NexusNodeFlagModel.node_id == f.node_id,
                NexusNodeFlagModel.flag_type == f.flag_type,
                NexusNodeFlagModel.subject_node_id == successor_id,
            )
        )
        if clash is not None:
            await session.delete(f)
    await session.flush()
    await simple("nexus_flags", NexusNodeFlagModel, "subject_node_id")

    # Metadatos propios del NOC: el nuevo hereda lo que el viejo tenía y el nuevo aún no.
    if old.is_favorite:
        new.is_favorite = True
    if old.is_ignored:
        new.is_ignored = True
    if old.is_nexus:
        new.is_nexus = True
    if new.preferred_gateway_id is None:
        new.preferred_gateway_id = old.preferred_gateway_id
    if new.node_type_override is None:
        new.node_type_override = old.node_type_override
    if old.first_seen_at is not None and (
        new.first_seen_at is None or _naive(old.first_seen_at) < _naive(new.first_seen_at)
    ):
        new.first_seen_at = old.first_seen_at

    await session.flush()
    await session.delete(old)
    await session.flush()
    return {k: v for k, v in moved.items() if v}


def _naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt
