"""Eventos de actividad backend→UI para la consola del operador.

Reutiliza el envelope v1 y el fan-out WebSocket existente (mismo patrón que el
broadcaster de alertas): NO es una segunda infraestructura de eventos. Estos
eventos son informativos para la UI; no viajan por Redis ni los consume el
tracker (que solo escucha el bus), por lo que no pueden producir bucles.

Vocabulario aditivo sobre `admin.operation` (estados de ciclo de vida que el
gateway no conoce: created, dispatched, retry_scheduled, finished) y un nuevo
event_type `admin.batch` para el ciclo de vida de los lotes. El resto de la
consola (pasarelas, alertas, malla) se alimenta de los eventos ya existentes.
"""

import logging
from typing import Any, Awaitable, Callable

from noc.application.envelopes import SYSTEM_SOURCE, make_event_envelope
from noc.domain.admin.entities import AdminBatch, AdminOperation

logger = logging.getLogger("noc.activity")

Publisher = Callable[[dict[str, Any]], Awaitable[None]]


class ActivityPublisher:
    """Puerta de salida de eventos de actividad. El callable real (el hub WS)
    se inyecta en el arranque; sin él, emitir es un no-op (tests, scripts)."""

    def __init__(self) -> None:
        self._publish: Publisher | None = None

    def attach(self, publish: Publisher | None) -> None:
        self._publish = publish

    async def emit(
        self, event_type: str, payload: dict[str, Any], gateway_id: str = SYSTEM_SOURCE
    ) -> None:
        if self._publish is None:
            return
        event = make_event_envelope(event_type, payload, gateway_id=gateway_id)
        try:
            await self._publish(event)
        except Exception:
            # La actividad nunca debe tumbar el pipeline
            logger.exception("activity emit failed (%s)", event_type)

    async def operation(self, op: AdminOperation, state: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "operation_id": op.id,
            "state": state,
            "node_id": op.target_node_id,
            "operation_type": op.operation_type,
            "batch_id": op.batch_id,
            "attempts": op.attempts,
            "max_attempts": op.max_attempts,
        }
        if isinstance(op.params, dict) and isinstance(op.params.get("section"), str):
            payload["section"] = op.params["section"]
        payload.update(extra)
        await self.emit("admin.operation", payload, gateway_id=op.gateway_id)

    async def batch(self, batch: AdminBatch, state: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "batch_id": batch.id,
            "state": state,
            "name": batch.name,
            "operation_type": batch.operation_type,
            "node_count": len(batch.node_ids),
        }
        payload.update(extra)
        await self.emit("admin.batch", payload)


# Instancia compartida: el arranque le adjunta el hub WS; sin adjuntar (tests,
# scripts) todas las emisiones son no-op. Evita acoplar handlers de FastAPI a
# Request solo para llegar a app.state.
activity = ActivityPublisher()
