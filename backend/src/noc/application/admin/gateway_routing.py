"""Enrutado de operaciones remotas por pasarela (M6.2, diseño §6).

Resuelve, EN EL MOMENTO DE ENCOLAR, por qué pasarela debe viajar una
operación de administración remota hacia un nodo. Reutiliza la única
función de ranking del proyecto (`gateway_link_selection.select_primary_link`,
M6.1) sobre los enlaces N:M de `node_gateway_links`, añadiendo el filtro de
candidatos válidos del diseño: solo pasarelas conectadas (heartbeat no stale),
habilitadas y no eliminadas, con enlace activo hacia el nodo.

Decisiones (confirmadas por el usuario al aprobar M6.2):
- La pasarela queda FIJADA cuando la operación entra en cola: no hay failover
  automático durante la vida de la operación (ADR 0013 prohíbe la doble
  ejecución sobre LoRa). El reintento manual del operador sí re-evalúa.
- Si ningún candidato pasa los filtros, se usa la caché `nodes.gateway_id`
  (pasarela primaria derivada) como fallback: con una sola pasarela esto es
  exactamente el comportamiento anterior a M6.2 (la operación se encola
  aunque la pasarela esté momentáneamente caída y se despachará cuando
  vuelva), garantizando cero regresión mono-pasarela.
- El fallback NO puede devolver una pasarela retirada de forma permanente:
  si su fila en `gateways` consta como eliminada (borrado lógico) o
  deshabilitada, se devuelve None (operación no enrutable). Solo se permite
  el fallback cuando la pasarela está operativa-pero-caída o cuando aún no
  tiene fila (nunca ha enviado heartbeat, p. ej. arranque en frío).
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNodeGatewayLinkRepository,
)
from noc.application.dashboard import is_stale
from noc.application.gateway_link_selection import GatewayLinkCandidate, select_primary_link
from noc.config import Settings
from noc.domain.nodes.entities import GatewayInfo, NodeGatewayLink


def _eligible_gateways(
    gateways: list[GatewayInfo], stale_after_seconds: int, now: datetime
) -> dict[str, GatewayInfo]:
    return {
        g.gateway_id: g
        for g in gateways
        if g.status == "connected"
        and g.enabled
        and g.deleted_at is None
        and not is_stale(g.updated_at, stale_after_seconds, now=now)
    }


def _fallback_allowed(fallback_gateway_id: str | None, known: dict[str, GatewayInfo]) -> str | None:
    """El fallback preserva el comportamiento mono-pasarela, pero nunca puede
    resucitar una pasarela retirada a propósito: eliminada (deleted_at) o
    deshabilitada. Sin fila en `gateways` (aún sin heartbeat) se permite."""
    if not fallback_gateway_id:
        return None
    info = known.get(fallback_gateway_id)
    if info is not None and (info.deleted_at is not None or not info.enabled):
        return None
    return fallback_gateway_id


def _select(
    links: list[NodeGatewayLink],
    eligible: dict[str, GatewayInfo],
    offline_after_seconds: int,
    now: datetime,
    fallback_gateway_id: str | None,
) -> str | None:
    candidates = [
        GatewayLinkCandidate(
            gateway_id=link.gateway_id,
            last_heard_at=link.last_heard_at,  # type: ignore[arg-type]
            priority=eligible[link.gateway_id].priority,
            hops_away=link.hops_away,
            snr=link.snr,
            rssi=link.rssi,
        )
        for link in links
        if link.gateway_id in eligible
        and link.last_heard_at is not None
        and not is_stale(link.last_heard_at, offline_after_seconds, now=now)
    ]
    winner = select_primary_link(candidates)
    return winner.gateway_id if winner is not None else fallback_gateway_id


async def select_gateways_for_nodes(
    session: AsyncSession,
    fallbacks: dict[str, str | None],
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, str | None]:
    """Resuelve la mejor pasarela para cada nodo de `fallbacks` (node_id ->
    `nodes.gateway_id` cacheado, usado si no hay candidato válido).

    Dos consultas en total, independiente del número de nodos.
    """
    now = now or datetime.now(timezone.utc)
    links_by_node = await SqlNodeGatewayLinkRepository(session).list_for_nodes(
        list(fallbacks.keys())
    )
    gateways = await SqlGatewayRepository(session).list_all(include_deleted=True)
    known = {g.gateway_id: g for g in gateways}
    eligible = _eligible_gateways(gateways, settings.gateway_stale_after_seconds, now)
    return {
        node_id: _select(
            links_by_node.get(node_id, []),
            eligible,
            settings.node_offline_after_seconds,
            now,
            _fallback_allowed(fallback, known),
        )
        for node_id, fallback in fallbacks.items()
    }


async def select_gateway_for_node(
    session: AsyncSession,
    node_id: str,
    settings: Settings,
    fallback_gateway_id: str | None = None,
    now: datetime | None = None,
) -> str | None:
    result = await select_gateways_for_nodes(
        session, {node_id: fallback_gateway_id}, settings, now=now
    )
    return result[node_id]
