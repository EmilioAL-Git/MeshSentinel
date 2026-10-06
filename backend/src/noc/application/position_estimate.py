"""Estimación de posición para nodos SIN GPS (ADR 0035). PURA.

Heurística honesta, no trilateración: centroide ponderado de las posiciones
de los nodos que lo oyeron DIRECTAMENTE, más un radio de incertidumbre. Cada
resultado es «inferido» (procedencia): la posición real y la manual siempre
mandan, y una estimación se descarta en cuanto el nodo informa de un GPS.

Anclas válidas (solo enlaces que acotan la distancia por alcance de radio):
- pasarela que lo oyó a 0 saltos → posición del nodo local de la pasarela
- enlace de vecinos / salto de traza (en cualquier sentido) con un nodo que
  SÍ tiene posición
Un nodo oído a ≥1 salto NO ancla nada: puede estar en cualquier parte.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from noc.application.dashboard import ensure_utc
from noc.application.rf_graph import RfEdge, haversine_m
from noc.domain.nodes.entities import GatewayInfo, NodeGatewayLink, NodeSummary

MAX_ANCHOR_AGE_HOURS = 48
BASE_RADIUS_M = 5000.0  # un solo ancla: alcance típico de un enlace directo
MIN_RADIUS_M = 800.0


@dataclass(slots=True, frozen=True)
class Anchor:
    lat: float
    lon: float
    snr: float | None
    age_hours: float
    source: str  # "gateway" | "link"


@dataclass(slots=True, frozen=True)
class Estimate:
    node_id: str
    latitude: float
    longitude: float
    radius_m: float
    anchors: int


def _weight(a: Anchor) -> float:
    snr = 0.5 if a.snr is None else min(1.5, max(0.1, (a.snr + 20.0) / 30.0))
    return snr * math.exp(-a.age_hours / 72.0)


def estimate_position(node_id: str, anchors: list[Anchor]) -> Estimate | None:
    if not anchors:
        return None
    weights = [_weight(a) for a in anchors]
    total = sum(weights)
    lat = sum(a.lat * w for a, w in zip(anchors, weights)) / total
    lon = sum(a.lon * w for a, w in zip(anchors, weights)) / total
    spread = max(haversine_m(lat, lon, a.lat, a.lon) for a in anchors)
    radius = min(BASE_RADIUS_M, max(MIN_RADIUS_M, BASE_RADIUS_M / math.sqrt(len(anchors)), 0.5 * spread))
    # ≥2 anclas muy separadas (> 2×alcance) no convergen: no hay estimación fiable
    if spread > 2 * BASE_RADIUS_M:
        return None
    return Estimate(node_id, lat, lon, round(radius), len(anchors))


def compute_estimates(
    summaries: list[NodeSummary],
    links: list[NodeGatewayLink],
    gateways: list[GatewayInfo],
    rf_edges: list[RfEdge],
    now: datetime,
) -> dict[str, Estimate]:
    pos = {
        s.node.node_id: (s.last_position.latitude, s.last_position.longitude)
        for s in summaries
        if s.last_position is not None
    }
    gw_node = {g.gateway_id: g.local_node_id for g in gateways if g.deleted_at is None and g.local_node_id}
    anchors: dict[str, list[Anchor]] = {}

    def age(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        return (now - ensure_utc(ts)).total_seconds() / 3600.0

    for link in links:
        if link.node_id in pos or link.hops_away != 0:
            continue
        local = gw_node.get(link.gateway_id)
        h = age(link.last_heard_at)
        if local is None or local not in pos or h is None or h > MAX_ANCHOR_AGE_HOURS or local == link.node_id:
            continue
        anchors.setdefault(link.node_id, []).append(Anchor(*pos[local], link.snr, h, "gateway"))

    for e in rf_edges:
        h = age(e.seen_at)
        if h is None or h > MAX_ANCHOR_AGE_HOURS:
            continue
        for lost, anchor in ((e.dst_id, e.src_id), (e.src_id, e.dst_id)):
            if lost not in pos and anchor in pos:
                anchors.setdefault(lost, []).append(Anchor(*pos[anchor], e.snr, h, "link"))

    out: dict[str, Estimate] = {}
    for node_id, items in anchors.items():
        est = estimate_position(node_id, items)
        if est is not None:
            out[node_id] = est
    return out
