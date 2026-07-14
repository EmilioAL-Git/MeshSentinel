"""Escritor en background del Registro persistente (fase de hardening).

`ActivityPublisher.emit_activity` se invoca a menudo DENTRO de la transacción
del llamante (la ingesta narra tras persistir, dentro de `session.begin()`).
Con SQLite (un solo escritor) abrir aquí una sesión propia e insertar en línea
se bloquearía contra esa transacción — por eso la persistencia es una cola
acotada + una tarea propia que inserta por lotes en su propia transacción,
fuera del camino crítico de ingesta y del fan-out WebSocket.

La cola descarta (con contador) si se llena: el Registro persistente es un
diario de operador, no un sistema de auditoría garantizada — nunca debe
ejercer backpressure sobre la ingesta (misma filosofía que la cola del
transporte del gateway, ADR 0009).
"""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.activity_repositories import SqlActivityLogRepository

logger = logging.getLogger("noc.activity.log")

QUEUE_MAX = 2000
BATCH_MAX = 200
# Poda cada N inserciones acumuladas (no cada lote: DELETE + subconsulta
# tienen coste; el tope de filas es orientativo, no exacto al instante)
PRUNE_EVERY = 500


class ActivityLogWriter:
    """Cola acotada -> INSERT por lotes -> poda periódica por tamaño máximo."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], max_rows: int
    ) -> None:
        self._session_factory = session_factory
        self._max_rows = max_rows
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._task: asyncio.Task[None] | None = None
        self._dropped = 0
        self._since_prune = 0

    def enqueue(self, envelope: dict[str, Any]) -> None:
        """No bloqueante y sin excepciones: apto para llamar desde el publisher."""
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.warning("activity_log queue full (dropped=%d)", self._dropped)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="activity-log-writer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Vaciado final: lo encolado durante el apagado no se pierde
        await self._flush(self._drain())

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            batch = [first, *self._drain(BATCH_MAX - 1)]
            try:
                await self._flush(batch)
            except asyncio.CancelledError:
                raise
            except Exception:
                # El Registro nunca tumba el proceso; el lote se pierde con log
                logger.exception("activity_log flush failed (%d events lost)", len(batch))

    def _drain(self, limit: int | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while limit is None or len(out) < limit:
            try:
                out.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    async def _flush(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        async with self._session_factory() as session, session.begin():
            repo = SqlActivityLogRepository(session)
            await repo.add_many(batch)
            self._since_prune += len(batch)
            if self._since_prune >= PRUNE_EVERY:
                self._since_prune = 0
                pruned = await repo.prune_to(self._max_rows)
                if pruned:
                    logger.info("activity_log pruned rows=%d (max=%d)", pruned, self._max_rows)
