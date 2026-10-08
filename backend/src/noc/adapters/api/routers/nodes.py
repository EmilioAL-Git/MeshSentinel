from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from noc.adapters.api.deps import CurrentUserDep, RequireAdminDep, RequireManagerDep, RequireUserDep, SessionDep
from noc.adapters.api.schemas import (
    NeighborOut,
    NodeGatewayLinkOut,
    NodeOut,
    NodeSummaryOut,
    NodeTypeBulkIn,
    NodeTypeIn,
    PositionOut,
    PreferredGatewayIn,
    TelemetryOut,
)
from noc.adapters.persistence.maintenance import reset_node_db
from noc.adapters.persistence.organization_repositories import SqlTagRepository, SqlUserFavoriteRepository
from noc.adapters.persistence.repositories import (
    SqlNeighborRepository,
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.application.node_filters import NodeFilters, apply_filters
from noc.config import get_settings

router = APIRouter(prefix="/nodes", tags=["nodes"])


class FlagIn(BaseModel):
    value: bool


class NodeTagsIn(BaseModel):
    tag_ids: list[int]


WIPE_NODES_CONFIRM = "BORRAR NODOS"


class WipeNodesIn(BaseModel):
    confirm: str


class WipeNodesOut(BaseModel):
    deleted: int
    alerts_deleted: int
    node_scoped_rules_deleted: int
    admin_operations_deleted: int
    admin_batches_deleted: int
    nexus_operations_deleted: int
    activity_log_deleted: int


async def _user_favorites(session, user) -> set[str]:
    if user is None or user.id is None:
        return set()
    return await SqlUserFavoriteRepository(session).ids_for_user(user.id)


@router.get("", response_model=list[NodeSummaryOut])
async def list_nodes(
    session: SessionDep,
    q: str | None = Query(default=None, max_length=64),
    hw_model: str | None = None,
    tag: str | None = None,
    group_id: int | None = None,
    favorite: bool | None = None,
    online: bool | None = None,
    battery_below: int | None = Query(default=None, ge=1, le=101),
    gateway_id: str | None = None,
    include_ignored: bool = False,
    only_ignored: bool = False,
    nexus: bool | None = None,
    current_user: CurrentUserDep = None,
) -> list[NodeSummaryOut]:
    threshold = get_settings().node_offline_after_seconds
    summaries = await SqlNodeRepository(session).list_summaries()
    # Favoritos PERSONALES (ADR 0029): `is_favorite` se rellena por usuario; sin
    # sesión nadie tiene favoritos. Antes del filtro, para que ?favorite= valga.
    favs = await _user_favorites(session, current_user)
    for s in summaries:
        s.node.is_favorite = s.node.node_id in favs
    # M6.2: observaciones por pasarela adjuntas al resumen (una sola consulta)
    links_by_node = await SqlNodeGatewayLinkRepository(session).list_for_nodes(
        [s.node.node_id for s in summaries]
    )
    filtered = apply_filters(
        summaries,
        NodeFilters(
            q=q,
            hw_model=hw_model,
            tag=tag,
            group_id=group_id,
            favorite=favorite,
            online=online,
            battery_below=battery_below,
            gateway_id=gateway_id,
            include_ignored=include_ignored,
            only_ignored=only_ignored,
            nexus=nexus,
        ),
        threshold,
    )
    return [
        NodeSummaryOut.from_entity(s, threshold, links_by_node.get(s.node.node_id))
        for s in filtered
    ]


@router.delete("", response_model=WipeNodesOut)
async def wipe_all_nodes(
    body: WipeNodesIn, session: SessionDep, _admin: RequireAdminDep
) -> WipeNodesOut:
    """Reinicio de fábrica de la NodeDB (mantenimiento, no config): nodos +
    su historia propia + TODO rastro histórico que dependía de ellos
    (alertas, operaciones/lotes de administración, operaciones Nexus, diario
    de actividad) — deja la instalación como recién salida de fábrica.
    Gateways/grupos/tags/reglas globales-o-por-grupo/canales/perfiles/
    usuarios/ajustes Nexus intactos (solo se borran las reglas escopadas a
    un nodo concreto, huérfanas sin él); la malla se redescubre sola con el
    próximo tráfico. Confirmación explícita por texto (mismo patrón que los
    SET destructivos de M1.3): evita un borrado de un solo clic."""
    if body.confirm != WIPE_NODES_CONFIRM:
        raise HTTPException(status_code=422, detail=f"Escribe «{WIPE_NODES_CONFIRM}» para confirmar")
    async with session.begin():
        counts = await reset_node_db(session)
    return WipeNodesOut(
        deleted=counts.nodes,
        alerts_deleted=counts.alerts,
        node_scoped_rules_deleted=counts.node_scoped_rules,
        admin_operations_deleted=counts.admin_operations,
        admin_batches_deleted=counts.admin_batches,
        nexus_operations_deleted=counts.nexus_operations,
        activity_log_deleted=counts.activity_log,
    )


class NodeBulkDeleteIn(BaseModel):
    node_ids: list[str]


class NodeBulkDeleteOut(BaseModel):
    deleted: int


@router.delete("/bulk", response_model=NodeBulkDeleteOut)
async def delete_nodes_bulk(
    body: NodeBulkDeleteIn, session: SessionDep, current_user: RequireManagerDep
) -> NodeBulkDeleteOut:
    """Borrado real de varios nodos a la vez (selección de Flota) — distinto
    de `DELETE /nodes` (borrado TOTAL de la NodeDB, solo admin)."""
    deleted = await SqlNodeRepository(session).delete_bulk(body.node_ids)
    await session.commit()
    return NodeBulkDeleteOut(deleted=deleted)


@router.delete("/{node_id}", status_code=204)
async def delete_node(node_id: str, session: SessionDep, current_user: RequireManagerDep) -> None:
    """Borrado real e irreversible de un nodo: fila + su historial propio
    (posiciones/telemetría/vecinos/tags/grupos/enlaces con pasarela/chat
    enviado). Distinto de `is_ignored` (M1.2), que solo lo oculta sin
    perder datos."""
    deleted = await SqlNodeRepository(session).delete(node_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()


@router.put("/{node_id}/favorite", response_model=NodeOut)
async def set_favorite(node_id: str, body: FlagIn, session: SessionDep, user: RequireUserDep) -> NodeOut:
    """Favorito PERSONAL del usuario con sesión (ADR 0029)."""
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await SqlUserFavoriteRepository(session).set_bulk(user.id or 0, [node_id], body.value)
    await session.commit()
    node.is_favorite = body.value
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


class FavoriteBulkIn(BaseModel):
    node_ids: list[str] = Field(min_length=1)
    value: bool = True


class FavoriteBulkOut(BaseModel):
    changed: int
    unchanged: int


# POST (no PUT /{node_id}/...): ruta de 1 segmento fijo, sin choque con
# /{node_id}/favorite.
@router.post("/bulk-favorite", response_model=FavoriteBulkOut)
async def set_favorite_bulk(
    body: FavoriteBulkIn, session: SessionDep, user: RequireUserDep
) -> FavoriteBulkOut:
    changed, unchanged = await SqlUserFavoriteRepository(session).set_bulk(
        user.id or 0, body.node_ids, body.value
    )
    await session.commit()
    return FavoriteBulkOut(changed=changed, unchanged=unchanged)


@router.put("/{node_id}/ignored", response_model=NodeOut)
async def set_ignored(node_id: str, body: FlagIn, session: SessionDep, _user: RequireManagerDep) -> NodeOut:
    node = await SqlNodeRepository(session).set_flag(node_id, "is_ignored", body.value)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.put("/{node_id}/alerts-muted", response_model=NodeOut)
async def set_alerts_muted(
    node_id: str, body: FlagIn, session: SessionDep, _user: RequireManagerDep
) -> NodeOut:
    """Silencia las alertas de ESTE nodo (sigue visible y cuenta en agregados)."""
    node = await SqlNodeRepository(session).set_flag(node_id, "alerts_muted", body.value)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.put("/{node_id}/nexus", response_model=NodeOut)
async def set_nexus(
    node_id: str, body: FlagIn, session: SessionDep, current_user: RequireManagerDep
) -> NodeOut:
    """Marcado manual de nodo JenTastic-Nexus (ADR 0027 §8) — enteramente
    manual, el operador confirma cada nodo (aceptando una sugerencia de
    `POST /nexus/scan` o marcándolo directamente); nunca se activa solo."""
    node = await SqlNodeRepository(session).set_flag(node_id, "is_nexus", body.value)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.put("/{node_id}/preferred-gateway", response_model=NodeOut)
async def set_node_preferred_gateway(
    node_id: str, body: PreferredGatewayIn, session: SessionDep, _user: RequireManagerDep
) -> NodeOut:
    """Nivel 2 de la selección inteligente de gateway (Inspector, sección Organización)."""
    node = await SqlNodeRepository(session).set_preferred_gateway(node_id, body.gateway_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.put("/{node_id}/node-type", response_model=NodeOut)
async def set_node_type(node_id: str, body: NodeTypeIn, session: SessionDep, _user: RequireManagerDep) -> NodeOut:
    """Clasificación manual (Inspector, Organización): null = "Automático",
    con prioridad absoluta sobre la clasificación derivada del role de
    firmware en cualquier otro caso (Flota, bloques, estadísticas de grupo)."""
    node = await SqlNodeRepository(session).set_node_type_override(node_id, body.node_type)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


class NodeTypeBulkOut(BaseModel):
    updated: int


@router.put("/node-type/bulk", response_model=NodeTypeBulkOut)
async def set_node_type_bulk(body: NodeTypeBulkIn, session: SessionDep, _user: RequireManagerDep) -> NodeTypeBulkOut:
    """Igual que set_node_type pero para la barra de selección de Flota."""
    updated = await SqlNodeRepository(session).set_node_type_override_bulk(
        body.node_ids, body.node_type
    )
    await session.commit()
    return NodeTypeBulkOut(updated=updated)


@router.put("/{node_id}/tags", status_code=204)
async def set_node_tags(node_id: str, body: NodeTagsIn, session: SessionDep, _user: RequireManagerDep) -> None:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await SqlTagRepository(session).set_node_tags(node_id, body.tag_ids)
    await session.commit()


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(node_id: str, session: SessionDep, current_user: CurrentUserDep) -> NodeOut:
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    node.is_favorite = node_id in await _user_favorites(session, current_user)
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.get("/{node_id}/positions", response_model=list[PositionOut])
async def node_positions(
    node_id: str, session: SessionDep, limit: int = Query(default=100, ge=1, le=1000)
) -> list[PositionOut]:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    positions = await SqlPositionRepository(session).list_for_node(node_id, limit)
    return [PositionOut.from_entity(p) for p in positions]


@router.get("/{node_id}/gateways", response_model=list[NodeGatewayLinkOut])
async def node_gateways(node_id: str, session: SessionDep) -> list[NodeGatewayLinkOut]:
    """Inspección de solo lectura de la relación N:M nodo<->pasarela (M6.1).

    No sustituye a `nodes.gateway_id` (la caché derivada que sigue usando el
    resto del sistema): expone TODAS las pasarelas que han oído a este nodo,
    orden por recepción más reciente.
    """
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    links = await SqlNodeGatewayLinkRepository(session).list_for_node(node_id)
    threshold = get_settings().node_offline_after_seconds
    return [NodeGatewayLinkOut.from_entity(link, threshold, node.gateway_id) for link in links]


@router.get("/{node_id}/neighbors", response_model=list[NeighborOut])
async def node_neighbors(node_id: str, session: SessionDep) -> list[NeighborOut]:
    """Vecindario actual real del nodo (NEIGHBORINFO_APP, motor-de-reglas-y-
    topologia.md §2): el ÚLTIMO enlace conocido por cada vecino, nunca el
    histórico con duplicados (la tabla es append-only; el histórico completo
    no tiene consumidor de UI hoy). Requiere que el firmware tenga el módulo
    activado; si no, queda vacío.
    """
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    neighbors = await SqlNeighborRepository(session).list_latest_for_node(node_id)
    threshold = get_settings().node_offline_after_seconds
    return [NeighborOut.from_entity(n, threshold) for n in neighbors]


@router.get("/{node_id}/telemetry", response_model=list[TelemetryOut])
async def node_telemetry(
    node_id: str,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=1000),
    kind: str | None = Query(default=None, pattern="^(device|environment|power)$"),
) -> list[TelemetryOut]:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    telemetry = await SqlTelemetryRepository(session).list_for_node(node_id, limit, kind)
    return [TelemetryOut.from_entity(t) for t in telemetry]
