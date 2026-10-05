from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from noc.adapters.api.deps import RequireManagerDep, SessionDep
from noc.adapters.api.schemas import TraceEdgeOut, TraceOut
from noc.adapters.persistence.trace_repository import SqlTraceRepository
from noc.application.dashboard import is_stale
from noc.application.traces_import import import_legacy_traces
from noc.config import get_settings

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("", response_model=list[TraceOut])
async def list_traces(
    session: SessionDep,
    node_id: str | None = None,
    operation_id: int | None = None,
    gateway_id: str | None = None,
    source: str | None = Query(default=None, pattern="^(active|passive)$"),
    reached: bool | None = None,
    since_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[TraceOut]:
    """Trazas recientes (más nuevas primero), de toda la red o las que tocan
    a un nodo (como origen o destino), o la de una operación concreta."""
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours) if since_hours else None
    rows = await SqlTraceRepository(session).list_recent(
        node_id=node_id,
        operation_id=operation_id,
        gateway_id=gateway_id,
        source=source,
        reached=reached,
        since=since,
        limit=limit
    )
    return [TraceOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/graph", response_model=list[TraceEdgeOut])
async def trace_graph(
    session: SessionDep, since_hours: int = Query(default=168, ge=1, le=24 * 365)
) -> list[TraceEdgeOut]:
    """Grafo acumulado de la red real: una arista DIRIGIDA por par (src, dst)
    con observaciones, SNR medio/mín/máx/último y primera/última vez vista,
    sumando todas las trazas de la ventana (activas y pasivas). Es el dato
    de entrada de cualquier representación (mapa, grafo, matriz...)."""
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    threshold = get_settings().node_offline_after_seconds
    edges = await SqlTraceRepository(session).graph(since=since)
    return [
        TraceEdgeOut(
            src_id=e.src_id,
            dst_id=e.dst_id,
            observations=e.observations,
            active_observations=e.active_observations,
            avg_snr=e.avg_snr,
            min_snr=e.min_snr,
            max_snr=e.max_snr,
            last_snr=e.last_snr,
            first_seen=e.first_seen,
            last_seen=e.last_seen,
            active=not is_stale(e.last_seen, threshold),
        )
        for e in edges
    ]


@router.post("/import-legacy")
async def import_legacy(session: SessionDep, _user: RequireManagerDep) -> dict[str, int]:
    """Rescata los traceroutes anteriores a ADR 0031 desde el Registro.
    Idempotente: repetirlo no duplica trazas."""
    stats = await import_legacy_traces(session)
    await session.commit()
    return stats


@router.get("/{trace_id}", response_model=TraceOut)
async def get_trace(trace_id: int, session: SessionDep) -> TraceOut:
    row = await SqlTraceRepository(session).get(trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Traza no encontrada")
    return TraceOut.model_validate(row, from_attributes=True)
