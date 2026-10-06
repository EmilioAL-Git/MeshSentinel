"""Cobertura medida (ADR 0035): recepciones directas agregadas por celda."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.repositories import SqlCoverageRepository

router = APIRouter(prefix="/coverage", tags=["coverage"])


class CoverageCellOut(BaseModel):
    latitude: float
    longitude: float
    avg_snr: float
    max_snr: float
    receptions: int
    nodes: int
    last_at: datetime | None


@router.get("", response_model=list[CoverageCellOut])
async def coverage(
    session: SessionDep,
    since_hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    gateway_id: str | None = Query(default=None, max_length=64),
) -> list[CoverageCellOut]:
    """Celdas de ~110 m con el SNR medio de las posiciones oídas A 0 SALTOS por
    una pasarela. Solo mide dónde HAY nodos con GPS emitiendo: ausencia de
    celda ≠ ausencia de cobertura."""
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cells = await SqlCoverageRepository(session).cells(since, gateway_id)
    return [CoverageCellOut(**c) for c in cells]
