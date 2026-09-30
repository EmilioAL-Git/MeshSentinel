"""Nombres reales de canal (índice LoRa -> nombre), fusionados entre pasarelas.

Cada pasarela lee su propia lista de canales del nodo local al conectar
(`gateway.channels`, cacheada en `gateways.channels`) — con varias pasarelas
pueden coexistir mallas con canales distintos o el mismo canal con nombres
divergentes. Función pura sobre `GatewayInfo` ya cargados (mismo patrón que
`gateway_stats.py`/`gateway_link_selection.py`): se resuelve el empate con el
mismo criterio ya establecido para "pasarela primaria" (`priority` manual,
ADR M6.1) y, en igualdad, `gateway_id` ascendente — así "la pasarela 1" gana
por defecto sin necesidad de fijar prioridades a mano.
"""

from noc.domain.nodes.entities import GatewayInfo


def merge_channel_names(gateways: list[GatewayInfo]) -> dict[int, str]:
    """Nombre de cada índice de canal, con la pasarela de mayor prioridad (y
    en empate, menor `gateway_id`) prevaleciendo; el resto solo aporta los
    índices que la primera no conoce."""
    ordered = sorted(gateways, key=lambda g: (-g.priority, g.gateway_id))
    merged: dict[int, str] = {}
    for gw in ordered:
        for ch in gw.channels:
            index = ch.get("index")
            name = (ch.get("name") or "").strip()
            if index is None or not name:
                continue
            merged.setdefault(int(index), name)
    return merged
