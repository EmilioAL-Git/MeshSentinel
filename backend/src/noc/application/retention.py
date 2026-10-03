"""Bucle de retención: aplica la poda por tipo de dato cada
`retention_interval_seconds` y a demanda (botón «Aplicar ahora»).

Lee los plazos de la instancia compartida de `Settings` en cada pasada, así
que un cambio hecho en Ajustes → Datos se aplica sin reiniciar. Una pasada
fallida nunca tumba el bucle: se registra y se reintenta en el siguiente
intervalo. Un cerrojo evita que una pasada manual se solape con la periódica.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.retention import prune_all
from noc.config import Settings

logger = logging.getLogger("noc.retention")

# Espera inicial: no competir con la ráfaga de arranque (snapshots NodeDB)
STARTUP_DELAY_SECONDS = 120


@dataclass(slots=True)
class RetentionRun:
    finished_at: datetime
    duration_seconds: float
    deleted: dict[str, int]
    trigger: str  # "scheduled" | "manual"
    error: str | None = None


@dataclass
class RetentionService:
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings
    last_run: RetentionRun | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._lock.locked()

    async def run_once(self, trigger: str = "manual") -> RetentionRun:
        async with self._lock:
            started = time.monotonic()
            error: str | None = None
            deleted: dict[str, int] = {}
            try:
                deleted = await prune_all(self.session_factory, self.settings)
            except Exception as exc:  # noqa: BLE001 — la poda nunca debe tumbar el proceso
                logger.exception("retention pass failed")
                error = str(exc) or exc.__class__.__name__
            run = RetentionRun(
                finished_at=datetime.now(timezone.utc),
                duration_seconds=round(time.monotonic() - started, 2),
                deleted=deleted,
                trigger=trigger,
                error=error,
            )
            self.last_run = run
            if any(deleted.values()):
                logger.info("retention %s deleted=%s in %.2fs", trigger, deleted, run.duration_seconds)
            return run

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="retention-loop")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(STARTUP_DELAY_SECONDS)
        while True:
            await self.run_once("scheduled")
            await asyncio.sleep(max(60, int(self.settings.retention_interval_seconds)))
