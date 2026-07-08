"""Búsqueda avanzada de nodos (M1.2): implementación única y reutilizable.

Función pura sobre los NodeSummary ya cargados (≤ cientos de filas): la usan
GET /nodes hoy y la reutilizarán las acciones masivas (alcance de batch) y los
grupos dinámicos del diseño del Módulo 1.
"""

from dataclasses import dataclass

from noc.domain.nodes.entities import NodeSummary


@dataclass(slots=True)
class NodeFilters:
    q: str | None = None  # subcadena sobre nombre corto/largo o node_id
    hw_model: str | None = None
    tag: str | None = None  # nombre de etiqueta
    group_id: int | None = None
    favorite: bool | None = None
    online: bool | None = None
    battery_below: int | None = None
    gateway_id: str | None = None
    include_ignored: bool = False
    only_ignored: bool = False

    @property
    def is_empty(self) -> bool:
        return self == NodeFilters()


def apply_filters(
    summaries: list[NodeSummary], filters: NodeFilters, online_threshold_seconds: int
) -> list[NodeSummary]:
    result = []
    needle = filters.q.lower() if filters.q else None
    for s in summaries:
        node = s.node
        if filters.only_ignored:
            if not node.is_ignored:
                continue
        elif node.is_ignored and not filters.include_ignored:
            continue
        if needle is not None:
            haystack = " ".join(
                x.lower() for x in (node.short_name, node.long_name, node.node_id) if x
            )
            if needle not in haystack:
                continue
        if filters.hw_model is not None and node.hw_model != filters.hw_model:
            continue
        if filters.tag is not None and filters.tag not in {t.name for t in s.tags}:
            continue
        if filters.group_id is not None and filters.group_id not in s.group_ids:
            continue
        if filters.favorite is not None and node.is_favorite != filters.favorite:
            continue
        if filters.online is not None and node.is_online(online_threshold_seconds) != filters.online:
            continue
        if filters.battery_below is not None:
            tel = s.last_device_telemetry
            battery = tel.battery_level if tel else None
            if battery is None or battery >= filters.battery_below:
                continue
        if filters.gateway_id is not None and node.gateway_id != filters.gateway_id:
            continue
        result.append(s)
    return result
