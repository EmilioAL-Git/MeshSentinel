"""Orquestación del pipeline de operaciones remotas (M1.1, diseño §4).

- Scheduler: despacha `pending` respetando presupuesto de malla (rate limit
  global) y 1 operación en vuelo por gateway; watchdog de operaciones colgadas.
- Tracker: consume eventos `admin.operation` del gateway y aplica la máquina de
  estados con reintentos (backoff exponencial) hasta max_attempts.
La cola es la BD (persistente, sobrevive reinicios); Redis Streams solo
transporta el comando al gateway.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.dashboard import ensure_utc
from noc.config import Settings
from noc.domain.admin.entities import AdminOperation

logger = logging.getLogger("noc.admin")

WATCHDOG_GRACE_SECONDS = 30
RETRY_BASE_SECONDS = 10
RETRY_MAX_SECONDS = 300


def retry_delay_seconds(attempts: int) -> float:
    return min(RETRY_BASE_SECONDS * (2 ** max(attempts - 1, 0)), RETRY_MAX_SECONDS)


class AdminOperationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: RedisCommandQueue,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        # M2: inyectado tras construir (attach_batch_service) para cerrar lotes
        self._batch_service: Any = None

    def attach_batch_service(self, batch_service: Any) -> None:
        self._batch_service = batch_service

    # ── Ciclo del scheduler ──────────────────────────────────────────────────

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="admin-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Admin scheduler tick failed")
            await asyncio.sleep(self._settings.admin_scheduler_interval_seconds)

    async def tick(self) -> None:
        """Un ciclo: watchdog + despacho (extraído para tests)."""
        now = datetime.now(timezone.utc)
        await self._expire_stuck(now)
        await self._dispatch(now)

    async def _expire_stuck(self, now: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            repo = SqlAdminOperationRepository(session)
            for op in await repo.list_expired_in_flight(now, WATCHDOG_GRACE_SECONDS):
                logger.warning("admin.op watchdog timeout id=%s node=%s", op.id, op.target_node_id)
                await self._apply_failure(
                    repo, op, "timeout", "watchdog: no result from gateway", now, session
                )

    async def _dispatch(self, now: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            repo = SqlAdminOperationRepository(session)
            window_start = now - timedelta(seconds=60)
            if await repo.count_dispatched_since(window_start) >= self._settings.admin_rate_limit_per_minute:
                return  # presupuesto de malla agotado en esta ventana
            op = await repo.next_dispatchable(now)
            if op is None:
                return
            op = await repo.update_fields(
                op.id or 0, {"status": "queued", "queued_at": now, "attempts": op.attempts + 1}
            )
        assert op is not None
        await self._queue.enqueue(op.gateway_id, self._command_envelope(op, now))
        logger.info(
            "admin.op dispatched id=%s type=%s node=%s attempt=%d/%d",
            op.id, op.operation_type, op.target_node_id, op.attempts, op.max_attempts,
        )

    def _command_envelope(self, op: AdminOperation, now: datetime) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "command_type": "command.send_admin",
            "command_id": str(uuid.uuid4()),
            "issued_by": op.created_by,
            "timestamp": now.isoformat(),
            "target_node_id": op.target_node_id,
            "payload": {
                "operation_id": op.id,
                "operation_type": op.operation_type,
                "params": op.params,
                "timeout_seconds": op.timeout_seconds,
            },
        }

    # ── Tracker: resultados del gateway ─────────────────────────────────────

    async def handle_event(self, event: dict[str, Any]) -> None:
        if event.get("event_type") != "admin.operation":
            return
        payload = event.get("payload") or {}
        op_id, state = payload.get("operation_id"), payload.get("state")
        if not isinstance(op_id, int) or state not in ("running", "succeeded", "failed", "timeout"):
            return
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session, session.begin():
            repo = SqlAdminOperationRepository(session)
            op = await repo.get(op_id)
            if op is None or op.is_terminal:
                return  # resultado tardío de una operación ya cerrada/cancelada
            if state == "running":
                await repo.update_fields(op_id, {"status": "running", "started_at": now})
            elif state == "succeeded":
                result = payload.get("result")
                status = self._map_success_status(result)
                await repo.update_fields(
                    op_id,
                    {
                        "status": status,
                        "result": result,
                        "finished_at": now,
                        "duration_ms": self._duration_ms(op, now),
                    },
                )
                logger.info("admin.op %s id=%s node=%s", status, op_id, op.target_node_id)
                await self._notify_batch(session, op)
            else:
                await self._apply_failure(repo, op, state, payload.get("error"), now, session)

    async def _notify_batch(self, session: Any, op: AdminOperation) -> None:
        """M2: si la operación pertenece a un lote, comprobar su finalización
        dentro de la misma transacción."""
        if op.batch_id is None or self._batch_service is None or session is None:
            return
        await self._batch_service.maybe_complete(session, op.batch_id)

    @staticmethod
    def _map_success_status(result: Any) -> str:
        """SETs verificables (M1.3, ADR 0014): el gateway reporta 'succeeded'
        por el contrato v1 y el veredicto viaja en result.verify — aquí se mapea
        al estado final. verify_failed y succeeded_unconfirmed son terminales
        y NO se reintentan (el SET pudo aplicarse; reintentar duplicaría
        escrituras en la malla)."""
        if isinstance(result, dict):
            verify = result.get("verify")
            if verify == "mismatch":
                return "verify_failed"
            if verify == "unavailable":
                return "succeeded_unconfirmed"
        return "succeeded"

    async def _apply_failure(
        self,
        repo: SqlAdminOperationRepository,
        op: AdminOperation,
        state: str,
        error: str | None,
        now: datetime,
        session: Any = None,
    ) -> None:
        if op.attempts < op.max_attempts:
            delay = retry_delay_seconds(op.attempts)
            await repo.update_fields(
                op.id or 0,
                {
                    "status": "pending",
                    "error": error,
                    "next_attempt_at": now + timedelta(seconds=delay),
                },
            )
            logger.info(
                "admin.op retry id=%s attempt=%d/%d in=%.0fs", op.id, op.attempts, op.max_attempts, delay
            )
        else:
            await repo.update_fields(
                op.id or 0,
                {
                    "status": state,
                    "error": error,
                    "finished_at": now,
                    "duration_ms": self._duration_ms(op, now),
                },
            )
            logger.warning("admin.op %s (final) id=%s node=%s", state, op.id, op.target_node_id)
            await self._notify_batch(session, op)

    @staticmethod
    def _duration_ms(op: AdminOperation, now: datetime) -> int | None:
        anchor = op.started_at or op.queued_at
        if anchor is None:
            return None
        return int((now - ensure_utc(anchor)).total_seconds() * 1000)
