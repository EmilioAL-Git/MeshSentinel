from fastapi import APIRouter, HTTPException, Query

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.schemas import NodeOut, NodeSummaryOut, PositionOut, TelemetryOut
from noc.adapters.persistence.repositories import (
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.config import get_settings

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", response_model=list[NodeSummaryOut])
async def list_nodes(session: SessionDep) -> list[NodeSummaryOut]:
    threshold = get_settings().node_offline_after_seconds
    summaries = await SqlNodeRepository(session).list_summaries()
    return [NodeSummaryOut.from_entity(s, threshold) for s in summaries]


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
