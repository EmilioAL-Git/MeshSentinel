from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.schemas import NodeOut, NodeSummaryOut, PositionOut, TelemetryOut
from noc.adapters.persistence.organization_repositories import SqlTagRepository
from noc.adapters.persistence.repositories import (
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
) -> list[NodeSummaryOut]:
    threshold = get_settings().node_offline_after_seconds
    summaries = await SqlNodeRepository(session).list_summaries()
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
        ),
        threshold,
    )
    return [NodeSummaryOut.from_entity(s, threshold) for s in filtered]


@router.put("/{node_id}/favorite", response_model=NodeOut)
async def set_favorite(node_id: str, body: FlagIn, session: SessionDep) -> NodeOut:
    node = await SqlNodeRepository(session).set_flag(node_id, "is_favorite", body.value)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.put("/{node_id}/ignored", response_model=NodeOut)
async def set_ignored(node_id: str, body: FlagIn, session: SessionDep) -> NodeOut:
    node = await SqlNodeRepository(session).set_flag(node_id, "is_ignored", body.value)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.put("/{node_id}/tags", status_code=204)
async def set_node_tags(node_id: str, body: NodeTagsIn, session: SessionDep) -> None:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await SqlTagRepository(session).set_node_tags(node_id, body.tag_ids)
    await session.commit()


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(node_id: str, session: SessionDep) -> NodeOut:
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeOut.from_entity(node, get_settings().node_offline_after_seconds)


@router.get("/{node_id}/positions", response_model=list[PositionOut])
async def node_positions(
    node_id: str, session: SessionDep, limit: int = Query(default=100, ge=1, le=1000)
) -> list[PositionOut]:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    positions = await SqlPositionRepository(session).list_for_node(node_id, limit)
    return [PositionOut.from_entity(p) for p in positions]


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
