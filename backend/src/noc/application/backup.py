"""Copias de seguridad programadas (ADR 0034).

Reutiliza `write_backup` (copia lógica JSONL+gzip, portable entre motores).
Sin tabla ni estado propio: "cuándo fue la última" se deduce de la fecha de
los ficheros del directorio, así que sobrevive a reinicios y a cambios de
periodicidad. Escritura atómica (temporal + rename: nunca queda una copia a
medias con nombre válido) y rotación por número de copias. Un fallo avisa a
las integraciones de notificación habilitadas — una copia que falla en
silencio es peor que no tenerla.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.notifications import build_provider
from noc.adapters.persistence.alert_repositories import SqlNotificationProviderRepository
from noc.adapters.persistence.backup import write_backup
from noc.application.alerting.message import NotificationMessage
from noc.config import Settings

logger = logging.getLogger("noc.backup")

STARTUP_DELAY_SECONDS = 180
CHECK_INTERVAL_SECONDS = 900
_NAME_RE = re.compile(r"^meshsentinel-\d{8}-\d{6}\.jsonl\.gz$")


@dataclass(slots=True)
class BackupFile:
    name: str
    size_bytes: int
    created_at: datetime


@dataclass(slots=True)
class BackupRun:
    finished_at: datetime
    duration_seconds: float
    trigger: str  # "scheduled" | "manual"
    file: str | None = None
    size_bytes: int | None = None
    error: str | None = None


def is_due(now: datetime, period_hours: int, newest: datetime | None) -> bool:
    """¿Toca hacer copia? Pura. Sin copias previas, toca en cuanto se activa."""
    if period_hours <= 0:
        return False
    return newest is None or now - newest >= timedelta(hours=period_hours)


@dataclass
class BackupService:
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings
    last_run: BackupRun | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _task: asyncio.Task[None] | None = None

    @property
    def directory(self) -> Path:
        return Path(self.settings.backup_dir)

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def list_backups(self) -> list[BackupFile]:
        if not self.directory.is_dir():
            return []
        out = []
        for p in self.directory.iterdir():
            if p.is_file() and _NAME_RE.match(p.name):
                st = p.stat()
                out.append(BackupFile(p.name, st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc)))
        return sorted(out, key=lambda f: f.created_at, reverse=True)

    def path_of(self, name: str) -> Path | None:
        """Ruta de una copia YA listada (nunca se compone con texto libre del cliente)."""
        return next((self.directory / f.name for f in self.list_backups() if f.name == name), None)

    def _rotate(self) -> list[str]:
        keep = max(1, int(self.settings.backup_keep))
        removed = []
        for f in self.list_backups()[keep:]:
            try:
                (self.directory / f.name).unlink()
                removed.append(f.name)
            except OSError:
                logger.warning("backup rotation could not remove %s", f.name)
        return removed

    async def run_once(self, trigger: str = "manual") -> BackupRun:
        async with self._lock:
            started = time.monotonic()
            now = datetime.now(timezone.utc)
            final = self.directory / f"meshsentinel-{now.strftime('%Y%m%d-%H%M%S')}.jsonl.gz"
            tmp = final.with_suffix(".tmp")
            run = BackupRun(finished_at=now, duration_seconds=0, trigger=trigger)
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                await write_backup(self.session_factory, tmp)
                tmp.replace(final)
                run.file, run.size_bytes = final.name, final.stat().st_size
                self._rotate()
            except Exception as exc:  # noqa: BLE001 — una copia fallida nunca tumba el proceso
                logger.exception("backup failed")
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass  # el directorio ni existe/es escribible: ya se informa el error original
                run.error = str(exc) or exc.__class__.__name__
            run.finished_at = datetime.now(timezone.utc)
            run.duration_seconds = round(time.monotonic() - started, 2)
            self.last_run = run
            if run.error:
                await self._notify_failure(run)
            else:
                logger.info("backup %s %s (%d bytes, %.1fs)", trigger, run.file, run.size_bytes, run.duration_seconds)
            return run

    async def _notify_failure(self, run: BackupRun) -> None:
        message = NotificationMessage(
            title="[ALERTA] La copia de seguridad ha fallado",
            severity="CRITICAL",
            kind="fired",
            subject_label="system:backup",
            body=f"MeshSentinel no pudo completar la copia {run.trigger}: {run.error}",
            occurred_at=run.finished_at,
        )
        try:
            async with self.session_factory() as session:
                providers = await SqlNotificationProviderRepository(session).list_enabled()
            for config in providers:
                provider = build_provider(config)
                if provider is None:
                    continue
                try:
                    await provider.send(message)
                except Exception:
                    logger.exception("backup failure notice failed provider=%s", config.name)
        except Exception:
            logger.exception("backup failure notification crashed")

    async def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        files = self.list_backups()
        if not is_due(now, int(self.settings.backup_period_hours), files[0].created_at if files else None):
            return False
        await self.run_once("scheduled")
        return True

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="backup-loop")

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
            try:
                await self.tick()
            except Exception:
                logger.exception("backup tick failed")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
