"""Selección de la pasarela primaria de un nodo (M6.1, diseño en
`docs/design/m6-multi-gateway.md` §3/§6).

Función pura, sin acceso a infraestructura: única fuente de la política de
ranking, reutilizada tanto para derivar la caché de `nodes` (M6.1) como,
en una fase futura (M6.4), para enrutar operaciones de administración remota.

Orden de criterios (confirmado por el usuario): prioridad manual de la
pasarela -> menos saltos -> mejor SNR -> mejor RSSI -> recepción más
reciente como último desempate.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class GatewayLinkCandidate:
    gateway_id: str
    last_heard_at: datetime
    priority: int = 0
    hops_away: int | None = None
    snr: float | None = None
    rssi: int | None = None


def _sort_key(candidate: GatewayLinkCandidate) -> tuple[int, float, float, float, float]:
    return (
        -candidate.priority,
        candidate.hops_away if candidate.hops_away is not None else float("inf"),
        -candidate.snr if candidate.snr is not None else float("inf"),
        -candidate.rssi if candidate.rssi is not None else float("inf"),
        -candidate.last_heard_at.timestamp(),
    )


def select_primary_link(
    candidates: list[GatewayLinkCandidate],
) -> GatewayLinkCandidate | None:
    """Elige la pasarela primaria entre los enlaces activos de un nodo.

    Con un único candidato (instalación de una sola pasarela) esto es
    siempre un no-op: devuelve ese candidato sin comparar nada.
    """
    if not candidates:
        return None
    return min(candidates, key=_sort_key)
