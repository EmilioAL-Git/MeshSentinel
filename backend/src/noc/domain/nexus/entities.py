"""Entidad de la cola persistente de operaciones JenTastic-Nexus (ADR 0027
§4). Sin dependencias de infraestructura."""

from dataclasses import dataclass, field
from datetime import datetime

PENDING = "pending"
SENT = "sent"
CONFIRMED = "confirmed"
NO_RESPONSE = "no_response"

TERMINAL_STATUSES = (CONFIRMED, NO_RESPONSE)


@dataclass(slots=True)
class NexusOperation:
    id: int | None = None
    gateway_id: str = ""
    # broadcast|local|node|mac|group — "device" deliberadamente ausente
    # (ADR 0027 §0.2: deshabilitado, no fiable en campo).
    target_kind: str = "broadcast"
    target_value: str | None = None  # shortname/mac/grupo; None en broadcast/local
    command_name: str = ""  # nombre canónico del catálogo (NexusCommand.spec.name)
    args: list[str] = field(default_factory=list)
    text: str = ""  # texto construido tal cual se envía, para auditoría
    destructive: bool = False
    requires_save: bool = False
    busy_seconds: float = 0.0
    status: str = PENDING
    created_by: str | None = None
    created_at: datetime | None = None
    sent_at: datetime | None = None
    response_at: datetime | None = None
    response_text: str | None = None
    response_kind: str | None = None  # "structured"|"raw"|"unsupported" (parsers.py)
    response_data: dict | None = None


@dataclass(slots=True)
class NexusOperationResponse:
    """UNA respuesta de UN nodo a una operación de destino múltiple
    (broadcast/group) — pedido explícito del usuario: mandar un comando a
    toda la malla Nexus del canal y ver a cada nodo responder por
    separado, no un único estado agregado. `operation.response_text/
    response_data` (arriba) sigue siendo el único-y-terminal para destinos
    dirigidos (local/node/mac); esta tabla existe SOLO para broadcast/
    group, donde puede haber N respuestas de N nodos distintos."""

    id: int | None = None
    operation_id: int = 0
    from_node_id: str = ""
    received_at: datetime | None = None
    response_text: str = ""
    response_kind: str = "raw"
    response_data: dict | None = None
