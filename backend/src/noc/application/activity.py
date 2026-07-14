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

from noc.application.activity_events import ActivityEvent, render_batch, render_operation
from noc.application.auth.actor import actor_label_for
from noc.application.envelopes import SYSTEM_SOURCE, make_event_envelope
from noc.domain.admin.entities import AdminBatch, AdminOperation

logger = logging.getLogger("noc.activity")

Publisher = Callable[[dict[str, Any]], Awaitable[None]]
# Resolución de etiqueta de nodo (short_name o node_id) para las narrativas
# admin; se inyecta en el arranque igual que el publisher. Sin ella, la
# narrativa usa el node_id crudo como etiqueta.
NodeLabeler = Callable[[str], Awaitable[str]]
# Persistencia del Registro (hardening): callable SÍNCRONO y no bloqueante
# (encola hacia ActivityLogWriter) — nunca una corrutina, para no acoplar la
# emisión a la latencia de la BD.
Store = Callable[[dict[str, Any]], None]


class ActivityPublisher:
    """Puerta de salida de eventos de actividad. El callable real (el hub WS)
    se inyecta en el arranque; sin él, emitir es un no-op (tests, scripts)."""

    def __init__(self) -> None:
        self._publish: Publisher | None = None
        self._labeler: NodeLabeler | None = None
        self._store: Store | None = None

    def attach(self, publish: Publisher | None) -> None:
        self._publish = publish

    def attach_labeler(self, labeler: NodeLabeler | None) -> None:
        self._labeler = labeler

    def attach_store(self, store: Store | None) -> None:
        self._store = store

    async def _label(self, node_id: str) -> str:
        if self._labeler is None:
            return node_id
        try:
            return await self._labeler(node_id)
        except Exception:
            logger.exception("node labeler failed (%s)", node_id)
            return node_id

    async def emit_activity(self, event: ActivityEvent) -> None:
        """Publica un hecho del diario operativo (Actividad 2.0 Fase 1) y lo
        persiste (hardening): un ÚNICO envelope para el WS y para la BD, de
        forma que el frontend siembre su buffer con el mismo parser."""
        envelope = make_event_envelope(
            "activity.event", event.to_payload(), gateway_id=event.gateway_id or SYSTEM_SOURCE
        )
        if self._store is not None:
            try:
                self._store(envelope)
            except Exception:
                logger.exception("activity store failed")
        await self._publish_envelope(envelope)

    async def emit(
        self, event_type: str, payload: dict[str, Any], gateway_id: str = SYSTEM_SOURCE
    ) -> None:
        await self._publish_envelope(make_event_envelope(event_type, payload, gateway_id=gateway_id))

    async def _publish_envelope(self, envelope: dict[str, Any]) -> None:
        if self._publish is None:
            return
        try:
            await self._publish(envelope)
        except Exception:
            # La actividad nunca debe tumbar el pipeline
            logger.exception("activity emit failed (%s)", envelope.get("event_type"))

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

        # Diario operativo (Actividad 2.0 Fase 1): el mismo hecho, narrado en
        # vocabulario de operador — coexiste con el evento técnico de arriba
        # (que siguen usando Trabajos/opTracker), nunca lo sustituye.
        narrative = render_operation(
            op.operation_type,
            state,
            op.target_node_id,
            await self._label(op.target_node_id),
            op.gateway_id,
            op.batch_id,
            final_status=extra.get("final_status"),
            verify=extra.get("verify"),
            error=extra.get("error"),
            attempts=op.attempts,
            max_attempts=op.max_attempts,
            actor_label=actor_label_for(op),
        )
        if narrative is not None:
            await self.emit_activity(narrative)

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

        narrative = render_batch(batch.id, batch.name, state, len(batch.node_ids), actor_label_for(batch))
        if narrative is not None:
            await self.emit_activity(narrative)


# Instancia compartida: el arranque le adjunta el hub WS; sin adjuntar (tests,
# scripts) todas las emisiones son no-op. Evita acoplar handlers de FastAPI a
# Request solo para llegar a app.state.
activity = ActivityPublisher()
