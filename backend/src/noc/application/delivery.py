"""Diagnóstico de entrega de un mensaje: «¿quién lo oyó?» (ADR 0034). PURO.

Un mismo paquete oído por N pasarelas genera N filas de `chat_messages` con
el mismo (`from_node_id`, `packet_id`). Aquí se agrupan y cada dato lleva su
PROCEDENCIA — nunca se inventa lo que no se sabe:

- reported:  campo del propio paquete (hop_limit, hop_start, canal, destino)
- observed:  lo midió una pasarela nuestra (SNR, RSSI, quién lo oyó, cuándo)
- inferred:  deducido de lo anterior (saltos usados = hop_start − hop_limit)
- unknown:   no disponible (p. ej. sin packet_id, o relé no decodificado)

Solo prueba que lo oyeron las pasarelas listadas: que el destino lo recibiese
NO se puede afirmar desde la recepción pasiva.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from noc.application.dashboard import ensure_utc
from noc.domain.chat.entities import ChatMessage

# El packet_id es de 32 bits y se reutiliza: solo se agrupan filas cercanas en el tiempo
SAME_PACKET_WINDOW = timedelta(minutes=10)

Provenance = str  # reported | observed | inferred | unknown


@dataclass(slots=True)
class Field:
    value: object | None
    provenance: Provenance


@dataclass(slots=True)
class HeardBy:
    gateway_id: str | None
    received_at: datetime | None
    snr: Field
    rssi: Field
    hop_limit: Field
    hop_start: Field
    hops_used: Field


@dataclass(slots=True)
class DeliveryDiagnostic:
    message_id: int
    packet_id: Field
    from_node_id: str
    to_node_id: Field
    channel_index: Field
    heard_by: list[HeardBy] = field(default_factory=list)
    heard_by_count: int = 0
    notes: list[str] = field(default_factory=list)


def _opt(value: object | None, provenance: Provenance) -> Field:
    return Field(value, provenance if value is not None else "unknown")


def _hops_used(m: ChatMessage) -> Field:
    # hop_start == 0 lo mandan firmwares antiguos sin el campo: no es "0 saltos"
    if m.hop_start is None or m.hop_limit is None or m.hop_start == 0:
        return Field(None, "unknown")
    return Field(max(0, m.hop_start - m.hop_limit), "inferred")


def _heard(m: ChatMessage) -> HeardBy:
    return HeardBy(
        gateway_id=m.gateway_id,
        received_at=m.received_at,
        snr=_opt(m.snr, "observed"),
        rssi=_opt(m.rssi, "observed"),
        hop_limit=_opt(m.hop_limit, "reported"),
        hop_start=_opt(m.hop_start, "reported"),
        hops_used=_hops_used(m),
    )


def build_delivery_diagnostic(message: ChatMessage, candidates: list[ChatMessage]) -> DeliveryDiagnostic:
    """`candidates`: filas con el mismo remitente y packet_id (incluida la propia)."""
    diag = DeliveryDiagnostic(
        message_id=message.id or 0,
        packet_id=_opt(message.packet_id, "reported"),
        from_node_id=message.from_node_id,
        to_node_id=Field(message.to_node_id, "reported") if message.to_node_id else Field("difusión", "inferred"),
        channel_index=Field(message.channel_index, "reported"),
    )
    if message.packet_id is None:
        diag.notes.append("Sin packet_id: no se pueden agrupar las pasarelas que lo oyeron (solo se muestra la propia).")
        rows = [message]
    else:
        anchor = ensure_utc(message.received_at) if message.received_at else None
        rows = [
            c
            for c in candidates
            if c.packet_id == message.packet_id
            and c.from_node_id == message.from_node_id
            and (
                anchor is None
                or c.received_at is None
                or abs(ensure_utc(c.received_at) - anchor) <= SAME_PACKET_WINDOW
            )
        ]
    rows.sort(key=lambda r: (ensure_utc(r.received_at).timestamp() if r.received_at else 0, r.gateway_id or ""))
    # Una misma pasarela puede repetir la fila (reconexión/reenvío): una por pasarela
    seen: set[str | None] = set()
    for r in rows:
        if r.gateway_id in seen:
            continue
        seen.add(r.gateway_id)
        diag.heard_by.append(_heard(r))
    diag.heard_by_count = len(diag.heard_by)
    diag.notes.append(
        "Solo consta la recepción por nuestras pasarelas; si el destino lo recibió no se puede saber desde aquí."
    )
    return diag
