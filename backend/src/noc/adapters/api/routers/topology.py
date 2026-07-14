from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.schemas import NeighborOut
from noc.adapters.persistence.repositories import SqlNeighborRepository
from noc.config import get_settings

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("", response_model=list[NeighborOut])
async def topology(
    session: SessionDep, since_hours: int = Query(default=24, ge=1, le=24 * 30)
) -> list[NeighborOut]:
    """Enlaces nodo<->nodo reales de toda la red (NEIGHBORINFO_APP), uno por
    par (node_id, neighbor_id) — endpoint agregado para pintar la capa
    "Enlaces (malla real)" del mapa sin N peticiones por nodo
    (motor-de-reglas-y-topologia.md §2). Vacío si ningún nodo tiene el
    módulo NeighborInfo activado por firmware.

    `since_hours` (24 por defecto) acota a enlaces oídos en esa ventana: sin
    ella, un par visto una sola vez se pintaría en gris para siempre.
    `active` sigue marcando los vigentes con el umbral de offline (~min).
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    links = await SqlNeighborRepository(session).list_latest_network(since=since)
    threshold = get_settings().node_offline_after_seconds
    return [NeighborOut.from_entity(link, threshold) for link in links]
