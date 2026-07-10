"""Estadísticas Multi-Gateway derivadas de `node_gateway_links` (M6.2, §11).

Función pura sobre datos ya cargados (mismo patrón que `compute_status` del
Dashboard): testeable sin BD y sin política propia — los conceptos de enlace
activo (umbral online/offline) y pasarela primaria (`nodes.gateway_id`,
derivada en M6.1) se reutilizan tal cual.
"""

from dataclasses import dataclass, field
from datetime import datetime

from noc.application.dashboard import is_stale
from noc.domain.nodes.entities import GatewayInfo, Node, NodeGatewayLink


@dataclass(slots=True)
class GatewayStats:
    gateway_id: str
    name: str | None
    status: str
    # Nodos con enlace ACTIVO hacia esta pasarela
    nodes_visible: int = 0
    # ... que ninguna otra pasarela oye ahora mismo
    nodes_exclusive: int = 0
    # ... que al menos otra pasarela también oye
    nodes_shared: int = 0
    # Nodos cuya pasarela primaria (nodes.gateway_id) es esta
    primary_for: int = 0
    # Última recepción de cualquier nodo por esta pasarela (aunque sea stale)
    last_heard_at: datetime | None = None


@dataclass(slots=True)
class MultiGatewayStats:
    generated_at: datetime
    # Nodos con al menos un enlace activo
    nodes_observed: int = 0
    # Nodos con >= 2 enlaces activos simultáneos
    nodes_shared: int = 0
    # % de nodos observados con cobertura redundante
    redundancy_percent: float = 0.0
    gateways: list[GatewayStats] = field(default_factory=list)


def compute_multi_gateway_stats(
    links: list[NodeGatewayLink],
    gateways: list[GatewayInfo],
    nodes: list[Node],
    offline_threshold_seconds: int,
    now: datetime,
) -> MultiGatewayStats:
    ignored = {n.node_id for n in nodes if n.is_ignored}
    primary_by_gateway: dict[str, int] = {}
    for n in nodes:
        if n.gateway_id and n.node_id not in ignored:
            primary_by_gateway[n.gateway_id] = primary_by_gateway.get(n.gateway_id, 0) + 1

    active_by_node: dict[str, set[str]] = {}
    last_heard: dict[str, datetime] = {}
    for link in links:
        if link.node_id in ignored:
            continue
        if link.last_heard_at is not None:
            prev = last_heard.get(link.gateway_id)
            if prev is None or link.last_heard_at > prev:
                last_heard[link.gateway_id] = link.last_heard_at
        if link.last_heard_at is not None and not is_stale(
            link.last_heard_at, offline_threshold_seconds, now=now
        ):
            active_by_node.setdefault(link.node_id, set()).add(link.gateway_id)

    shared_nodes = {n for n, gws in active_by_node.items() if len(gws) >= 2}

    stats: list[GatewayStats] = []
    for g in sorted(gateways, key=lambda g: g.gateway_id):
        if g.deleted_at is not None:
            continue
        visible = [n for n, gws in active_by_node.items() if g.gateway_id in gws]
        shared = [n for n in visible if n in shared_nodes]
        stats.append(
            GatewayStats(
                gateway_id=g.gateway_id,
                name=g.name,
                status=g.status,
                nodes_visible=len(visible),
                nodes_exclusive=len(visible) - len(shared),
                nodes_shared=len(shared),
                primary_for=primary_by_gateway.get(g.gateway_id, 0),
                last_heard_at=last_heard.get(g.gateway_id),
            )
        )

    observed = len(active_by_node)
    return MultiGatewayStats(
        generated_at=now,
        nodes_observed=observed,
        nodes_shared=len(shared_nodes),
        redundancy_percent=round(100.0 * len(shared_nodes) / observed, 1) if observed else 0.0,
        gateways=stats,
    )
