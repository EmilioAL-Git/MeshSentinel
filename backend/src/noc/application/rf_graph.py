"""Grafo RF a partir de lo que ya observamos (ADR 0035). PURO.

Dos fuentes de enlaces DIRIGIDOS (quién transmite → quién recibe, con el SNR
medido en el receptor):
- NeighborInfo (`node_neighbors`): el nodo N declara que oyó al vecino V con
  SNR s → arista V→N.
- Trazas (`node_trace_hops`): cada salto src→dst con su SNR.

Si un par aparece por las dos fuentes se conserva la observación más reciente.
Sin NeighborInfo activado en el firmware ni trazas, el grafo está vacío y las
reglas que lo usan simplemente no disparan (no hay línea base que juzgar).
"""

import math
from dataclasses import dataclass
from datetime import datetime

from noc.domain.nodes.entities import NodeNeighbor


@dataclass(slots=True, frozen=True)
class RfEdge:
    src_id: str
    dst_id: str
    snr: float
    seen_at: datetime | None
    source: str  # "neighbor" | "trace"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_rf_edges(
    neighbors: list[NodeNeighbor], trace_edges: list[tuple[str, str, float | None, datetime | None]]
) -> list[RfEdge]:
    """`trace_edges`: (src, dst, snr_medio, última_vez). Aristas sin SNR se descartan."""
    best: dict[tuple[str, str], RfEdge] = {}

    def offer(edge: RfEdge) -> None:
        key = (edge.src_id, edge.dst_id)
        prev = best.get(key)
        if prev is None or (edge.seen_at and (prev.seen_at is None or _naive(edge.seen_at) > _naive(prev.seen_at))):
            best[key] = edge

    for n in neighbors:
        if n.snr is not None:
            offer(RfEdge(n.neighbor_id, n.node_id, float(n.snr), n.received_at, "neighbor"))
    for src, dst, snr, seen in trace_edges:
        if snr is not None and src != dst:
            offer(RfEdge(src, dst, float(snr), seen, "trace"))
    return list(best.values())


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


@dataclass(slots=True, frozen=True)
class AsymmetricLink:
    weak_rx: str  # el extremo que oye PEOR
    strong_rx: str
    weak_snr: float
    strong_snr: float

    @property
    def delta_db(self) -> float:
        return self.strong_snr - self.weak_snr


def find_asymmetric_links(edges: list[RfEdge], min_delta_db: float) -> list[AsymmetricLink]:
    """Pares con observación en AMBOS sentidos cuyo SNR difiere más de `min_delta_db`."""
    by_dir = {(e.src_id, e.dst_id): e for e in edges}
    out: list[AsymmetricLink] = []
    seen: set[frozenset[str]] = set()
    for (a, b), ab in by_dir.items():
        ba = by_dir.get((b, a))
        pair = frozenset((a, b))
        if ba is None or pair in seen:
            continue
        seen.add(pair)
        if abs(ab.snr - ba.snr) < min_delta_db:
            continue
        # ab.snr = SNR con el que `b` oye a `a`
        weak, strong = (ab, ba) if ab.snr < ba.snr else (ba, ab)
        out.append(AsymmetricLink(weak.dst_id, strong.dst_id, weak.snr, strong.snr))
    return sorted(out, key=lambda x: (x.weak_rx, x.strong_rx))


def router_neighbors(edges: list[RfEdge], routers: set[str]) -> dict[str, set[str]]:
    """Para cada router, los OTROS routers con los que tiene enlace en cualquier sentido."""
    adj: dict[str, set[str]] = {r: set() for r in routers}
    for e in edges:
        if e.src_id in routers and e.dst_id in routers and e.src_id != e.dst_id:
            adj[e.src_id].add(e.dst_id)
            adj[e.dst_id].add(e.src_id)
    return adj
