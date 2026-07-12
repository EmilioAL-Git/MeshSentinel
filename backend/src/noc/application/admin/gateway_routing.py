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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.organization_repositories import SqlGroupRepository
from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
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


# ── Selección inteligente de gateway (jerarquía de 4 niveles) ────────────────
#
# Única función de resolución de todo el proyecto — cualquier código que
# encole una operación remota pasa por aquí, nunca por `select_gateway(s)_
# for_node(s)` directamente (esas dos siguen existiendo como el Nivel 4 puro,
# reutilizado sin cambios).
#
#   Nivel 1 — forced_gateway_id: el operador fuerza una pasarela concreta
#             para ESTA operación. Se usa siempre, sin comprobar disponibilidad
#             (decisión deliberada del operador, no una preferencia blanda).
#   Nivel 2 — node.preferred_gateway_id: preferencia del nodo (Inspector).
#   Nivel 3 — group.preferred_gateway_id: preferencia heredada del grupo
#             (el de menor id, si el nodo pertenece a varios con preferencias
#             distintas — desempate determinista, ver `preferred_gateway_for_node`).
#   Nivel 4 — algoritmo automático de M6.2 (select_gateways_for_nodes).
#
# Los niveles 2/3 son preferencias BLANDAS: si la pasarela preferida no está
# operativa (conectada, habilitada, no eliminada, heartbeat fresco — mismo
# criterio que siempre, `_eligible_gateways`), se cae automáticamente al
# Nivel 4 y se devuelve una `note` legible para el operador. Solo se
# devuelve `gateway_id=None` cuando NINGÚN nivel produce una pasarela
# operativa (red sin pasarelas o todas caídas).

GatewaySource = Literal["forced", "node_preferred", "group_preferred", "auto"]


@dataclass(slots=True)
class GatewayResolution:
    gateway_id: str | None
    source: GatewaySource
    note: str | None = None


async def resolve_gateways_for_nodes(
    session: AsyncSession,
    node_ids: list[str],
    settings: Settings,
    *,
    forced_gateway_id: str | None = None,
    use_preference: bool = True,
    now: datetime | None = None,
) -> dict[str, GatewayResolution]:
    """Versión en bloque de `resolve_gateway`: coste de consultas constante,
    independiente del número de nodos (igual disciplina que
    `select_gateways_for_nodes`) — usada por lotes y sincronización de perfiles."""
    now = now or datetime.now(timezone.utc)
    if not node_ids:
        return {}

    if forced_gateway_id:
        return {nid: GatewayResolution(gateway_id=forced_gateway_id, source="forced") for nid in node_ids}

    nodes_by_id = {n.node_id: n for n in await SqlNodeRepository(session).list_for_ids(node_ids)}

    # (gateway_id preferido, origen) por nodo — solo si Nivel 2/3 aplica
    preferred_by_node: dict[str, tuple[str, GatewaySource]] = {}
    if use_preference:
        group_prefs = await SqlGroupRepository(session).preferred_gateways_for_nodes(node_ids)
        for nid in node_ids:
            node = nodes_by_id.get(nid)
            if node is not None and node.preferred_gateway_id:
                preferred_by_node[nid] = (node.preferred_gateway_id, "node_preferred")
            elif nid in group_prefs:
                preferred_by_node[nid] = (group_prefs[nid], "group_preferred")

    gateways = await SqlGatewayRepository(session).list_all(include_deleted=True)
    eligible = _eligible_gateways(gateways, settings.gateway_stale_after_seconds, now)

    result: dict[str, GatewayResolution] = {}
    need_auto: dict[str, str | None] = {}
    for nid in node_ids:
        node = nodes_by_id.get(nid)
        fallback = node.gateway_id if node is not None else None
        if nid in preferred_by_node:
            pref_id, source = preferred_by_node[nid]
            if pref_id in eligible:
                result[nid] = GatewayResolution(gateway_id=pref_id, source=source)
                continue
        need_auto[nid] = fallback

    if need_auto:
        auto_results = await select_gateways_for_nodes(session, need_auto, settings, now=now)
        for nid, auto_id in auto_results.items():
            if nid in preferred_by_node:
                pref_id, _source = preferred_by_node[nid]
                note = (
                    f"Gateway preferido {pref_id} no disponible. Usando {auto_id} automáticamente."
                    if auto_id
                    else f"Gateway preferido {pref_id} no disponible y no hay alternativa operativa."
                )
                result[nid] = GatewayResolution(gateway_id=auto_id, source="auto", note=note)
            else:
                result[nid] = GatewayResolution(gateway_id=auto_id, source="auto")
    return result


async def resolve_gateway(
    session: AsyncSession,
    node_id: str,
    settings: Settings,
    *,
    forced_gateway_id: str | None = None,
    use_preference: bool = True,
    now: datetime | None = None,
) -> GatewayResolution:
    """Resuelve la pasarela final para UN nodo, aplicando la jerarquía de 4
    niveles. Único punto de entrada recomendado — delega en la versión en
    bloque para no duplicar la lógica."""
    result = await resolve_gateways_for_nodes(
        session, [node_id], settings, forced_gateway_id=forced_gateway_id, use_preference=use_preference, now=now
    )
    return result[node_id]
