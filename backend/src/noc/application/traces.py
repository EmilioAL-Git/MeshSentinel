"""Trazas de la red real (traceroute) — núcleo puro, sin SQL ni I/O.

Una *traza* es el camino que un paquete recorrió entre dos nodos: origen,
saltos intermedios y destino, con el SNR medido en cada salto, ida y vuelta.
Llega por dos vías que producen EL MISMO dato:

- **Pasiva**: cualquier TRACEROUTE_APP que la pasarela oiga (respuesta a un
  traceroute lanzado por ella, o paquete dirigido a su nodo local).
- **Activa**: el resultado de la operación `traceroute.run` (incluido el
  «sin respuesta», que es evidencia negativa útil).

Este módulo solo transforma: de cualquiera de las dos a un `TraceRecord`
(la traza) y sus `TraceHop` (una arista dirigida por salto, que es lo que
luego se agrega para dibujar el grafo). Ver ADR 0031.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# El firmware rellena con 0xffffffff los saltos cuyo id no puede revelar
UNKNOWN_NODE = "!ffffffff"

TraceSource = Literal["active", "passive"]
TraceKind = Literal["reply", "request", "no_response"]
HopDirection = Literal["towards", "back"]


@dataclass(slots=True, frozen=True)
class TraceHop:
    """Un salto dirigido src -> dst (el SNR se midió en dst al recibir de src)."""

    src: str
    dst: str
    snr: float | None
    direction: HopDirection
    position: int  # índice del salto dentro del sentido


@dataclass(slots=True)
class TraceRecord:
    gateway_id: str | None
    origin_id: str
    target_id: str
    source: TraceSource
    kind: TraceKind
    reached: bool
    received_at: datetime
    route: list[str] = field(default_factory=list)  # intermedios origen->destino
    route_back: list[str] = field(default_factory=list)  # intermedios destino->origen
    snr_towards: list[float | None] = field(default_factory=list)
    snr_back: list[float | None] = field(default_factory=list)
    operation_id: int | None = None
    # True = construida a partir de un paquete LoRa oído (no de un resultado)
    from_packet: bool = False
    hops: list[TraceHop] = field(default_factory=list)


def _leg_hops(
    path: list[str], snrs: list[float | None], direction: HopDirection
) -> list[TraceHop]:
    hops: list[TraceHop] = []
    for i in range(len(path) - 1):
        src, dst = path[i], path[i + 1]
        # Un salto con un extremo desconocido o degenerado no es una arista
        if UNKNOWN_NODE in (src, dst) or src == dst:
            continue
        snr = snrs[i] if i < len(snrs) else None
        hops.append(TraceHop(src=src, dst=dst, snr=snr, direction=direction, position=i))
    return hops


def extract_hops(
    origin: str,
    target: str,
    route: list[str],
    snr_towards: list[float | None],
    route_back: list[str],
    snr_back: list[float | None],
) -> list[TraceHop]:
    """Aristas dirigidas de la traza.

    `route`/`route_back` listan SOLO los intermedios (vacío = directo), así
    que el camino completo es origen + intermedios + destino. `snr_towards[i]`
    es el SNR con que `path[i+1]` oyó a `path[i]` (len = intermedios + 1)."""
    hops = _leg_hops([origin, *route, target], snr_towards, "towards")
    if route_back or snr_back:
        hops += _leg_hops([target, *route_back, origin], snr_back, "back")
    return hops


def _clean(values: Any) -> list[Any]:
    return list(values) if isinstance(values, list) else []


def trace_from_packet(
    payload: dict[str, Any],
    *,
    gateway_id: str | None,
    local_node_id: str | None,
    received_at: datetime,
) -> TraceRecord | None:
    """`traceroute.completed` -> traza, o None si no se puede orientar.

    En una RESPUESTA el emisor del paquete es el destino de la traza y el
    destinatario quien la lanzó; en la PETICIÓN, al revés. Si el paquete no
    trae destinatario se asume el nodo local de la pasarela (la API solo
    entrega paquetes dirigidos a él)."""
    sender = payload.get("node_id")
    other = payload.get("to_node_id") or local_node_id
    if not sender or not other or sender == other:
        return None
    is_reply = bool(payload.get("is_reply"))
    origin, target = (other, sender) if is_reply else (sender, other)
    route = _clean(payload.get("route"))
    route_back = _clean(payload.get("route_back"))
    snr_towards = _clean(payload.get("snr_towards"))
    snr_back = _clean(payload.get("snr_back"))
    return TraceRecord(
        gateway_id=gateway_id,
        origin_id=origin,
        target_id=target,
        source="passive",
        kind="reply" if is_reply else "request",
        reached=True,
        received_at=received_at,
        route=route,
        route_back=route_back,
        snr_towards=snr_towards,
        snr_back=snr_back,
        from_packet=True,
        hops=extract_hops(origin, target, route, snr_towards, route_back, snr_back),
    )


def trace_from_operation(
    result: dict[str, Any],
    *,
    operation_id: int,
    gateway_id: str | None,
    local_node_id: str | None,
    target_id: str,
    finished_at: datetime,
) -> TraceRecord | None:
    """Resultado de `traceroute.run` -> traza. Origen = nodo local de la
    pasarela que la lanzó (sin él no hay forma honesta de orientarla)."""
    if not local_node_id or local_node_id == target_id:
        return None
    reached = bool(result.get("reached"))
    route = _clean(result.get("route"))
    route_back = _clean(result.get("route_back"))
    snr_towards = _clean(result.get("snr_towards"))
    snr_back = _clean(result.get("snr_back"))
    return TraceRecord(
        gateway_id=gateway_id,
        origin_id=local_node_id,
        target_id=target_id,
        source="active",
        kind="reply" if reached else "no_response",
        reached=reached,
        received_at=finished_at,
        route=route,
        route_back=route_back,
        snr_towards=snr_towards,
        snr_back=snr_back,
        operation_id=operation_id,
        from_packet=False,
        hops=(
            extract_hops(local_node_id, target_id, route, snr_towards, route_back, snr_back)
            if reached
            else []
        ),
    )


def _legacy_snr(values: Any) -> list[float | None]:
    """El Registro anterior a ADR 0031 guardó `snr_towards` tal cual lo manda el
    firmware (cuartos de dB, -128 = desconocido)."""
    out: list[float | None] = []
    for v in _clean(values):
        out.append(None if not isinstance(v, (int, float)) or v == -128 else round(v / 4, 2))
    return out


def trace_from_legacy_activity(
    raw: dict[str, Any],
    *,
    gateway_id: str | None,
    local_node_id: str | None,
    received_at: datetime,
) -> TraceRecord | None:
    """Entrada antigua del Registro (TRACEROUTE_APP) -> traza, en lo posible.

    Aproximación asumida: el paquete es una RESPUESTA a un traceroute lanzado
    desde el nodo local de la pasarela (lo normal: la API solo entrega paquetes
    dirigidos a ese nodo). Se recupera la ida; la vuelta no se guardaba. Las
    entradas que ya llevan `is_reply` se registraron en vivo y se omiten."""
    if "is_reply" in raw:
        return None
    target = raw.get("node_id")
    if not target or not local_node_id or target == local_node_id:
        return None
    route = _clean(raw.get("route"))
    snr_towards = _legacy_snr(raw.get("snr_towards"))
    return TraceRecord(
        gateway_id=gateway_id,
        origin_id=local_node_id,
        target_id=target,
        source="passive",
        kind="reply",
        reached=True,
        received_at=received_at,
        route=route,
        snr_towards=snr_towards,
        from_packet=True,
        hops=extract_hops(local_node_id, target, route, snr_towards, [], []),
    )
