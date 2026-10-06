"""Posiciones estimadas para nodos sin GPS (ADR 0035). Solo lectura."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.models import EstimatedPositionModel

router = APIRouter(prefix="/estimated-positions", tags=["positions"])


class EstimatedPositionOut(BaseModel):
    node_id: str
    latitude: float
    longitude: float
    radius_m: int
    anchors: int
    computed_at: datetime
    provenance: str = "inferred"


@router.get("", response_model=list[EstimatedPositionOut])
async def list_estimated(session: SessionDep) -> list[EstimatedPositionOut]:
    """Una por nodo sin GPS con anclas suficientes. Siempre INFERIDA: la
    posición real y la manual mandan (el cliente las pinta antes)."""
    rows = (await session.scalars(select(EstimatedPositionModel))).all()
    return [
        EstimatedPositionOut(
            node_id=r.node_id, latitude=r.latitude, longitude=r.longitude,
            radius_m=r.radius_m, anchors=r.anchors, computed_at=r.computed_at,
        )
        for r in rows
    ]
