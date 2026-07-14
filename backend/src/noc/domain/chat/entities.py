"""Chat: monitor profesional de TEXT_MESSAGE_APP (mismo paquete que narra
Actividad 2.0 — ver `application/ingest.py:_on_message`). Sin dependencias de
infraestructura.
"""

from dataclasses import dataclass
from datetime import datetime

# "inbound" = oído en la malla (todo lo que existe hoy). "outbound" queda
# preparado para una fase futura de envío desde MeshSentinel sin migrar la
# tabla — ver ChatMessage.delivery_status.
Direction = str


@dataclass(slots=True)
class ChatMessage:
    from_node_id: str
    text: str
    to_node_id: str | None = None  # None = difusión
    channel_index: int = 0
    # Nombre real de canal: fase futura (lectura de localNode.channels, igual
    # que el comentario equivalente en activity_events.render_message). None
    # hasta entonces — el frontend cae a "Canal N".
    channel_name: str | None = None
    gateway_id: str | None = None
    rssi: int | None = None
    snr: float | None = None
    hops_away: int | None = None
    hop_limit: int | None = None
    hop_start: int | None = None
    # Indeterminable hoy a partir del paquete ya decodificado por la
    # librería (si estaba cifrado, ya se descifró antes de llegar aquí) —
    # reservado para cuando se pueda derivar del canal/PSK real.
    encrypted: bool | None = None
    packet_id: int | None = None
    direction: Direction = "inbound"
    # Reservados para "enviar mensajes" (fase futura, sin implementar):
    # delivery_status solo aplica a direction="outbound" (queued/sent/
    # delivered/failed); reply_to_id prepara "responder a mensaje";
    # actor_id identifica al operador que lo envió (auth_users.id).
    delivery_status: str | None = None
    reply_to_id: int | None = None
    actor_id: int | None = None
    raw: dict | None = None
    id: int | None = None
    received_at: datetime | None = None
