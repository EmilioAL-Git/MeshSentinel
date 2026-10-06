"""Mantenimiento de datos: almacenamiento, retención a demanda y salud del
propio proceso MeshSentinel. Solo administradores (mismo criterio que el reinicio de
la NodeDB y la importación de configuración)."""

import asyncio
from datetime import datetime

import os
import tempfile
from datetime import timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel

from noc.adapters.api.deps import RequireAdminDep, SessionDep
from noc.adapters.api.ws import hub
from noc.adapters.persistence.backup import write_backup
from noc.adapters.persistence.retention import TARGETS, storage_stats
from noc.application.retention import RetentionRun
from noc.config import get_settings

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class TableStatsOut(BaseModel):
    table: str
    label: str
    rows: int
    bytes: int | None
    oldest: datetime | None


class PolicyOut(BaseModel):
    key: str
    label: str
    setting: str
    days: int
    tables: list[str]
    rows: int
    bytes: int | None
    oldest: datetime | None


class RetentionRunOut(BaseModel):
    finished_at: datetime
    duration_seconds: float
    deleted: dict[str, int]
    trigger: str
    error: str | None


class StorageOut(BaseModel):
    engine: str
    total_bytes: int | None
    tables: list[TableStatsOut]
    policies: list[PolicyOut]
    last_run: RetentionRunOut | None
    running: bool


def _run_out(run: RetentionRun | None) -> RetentionRunOut | None:
    if run is None:
        return None
    return RetentionRunOut(
        finished_at=run.finished_at,
        duration_seconds=run.duration_seconds,
        deleted=run.deleted,
        trigger=run.trigger,
        error=run.error,
    )


@router.get("/storage", response_model=StorageOut)
async def get_storage(request: Request, session: SessionDep, _admin: RequireAdminDep) -> StorageOut:
    stats = await storage_stats(session)
    settings = get_settings()
    by_table = {t.table: t for t in stats.tables}
    policies = []
    for target in TARGETS:
        covered = [by_table[n] for n in target.tables if n in by_table]
        sizes = [t.bytes for t in covered if t.bytes is not None]
        oldests = [t.oldest for t in covered if t.oldest is not None]
        policies.append(
            PolicyOut(
                key=target.key,
                label=target.label,
                setting=target.setting,
                days=int(getattr(settings, target.setting)),
                tables=list(target.tables),
                rows=sum(t.rows for t in covered),
                bytes=sum(sizes) if sizes else None,
                oldest=min(oldests) if oldests else None,
            )
        )
    service = request.app.state.retention
    return StorageOut(
        engine=stats.engine,
        total_bytes=stats.total_bytes,
        tables=[TableStatsOut(**vars_of(t)) for t in stats.tables],
        policies=policies,
        last_run=_run_out(service.last_run),
        running=service.running,
    )


def vars_of(t: object) -> dict[str, object]:
    return {f: getattr(t, f) for f in TableStatsOut.model_fields}


@router.post("/prune", response_model=RetentionRunOut)
async def prune_now(request: Request, _admin: RequireAdminDep) -> RetentionRunOut:
    """Aplica ya las políticas vigentes (no espera al bucle periódico)."""
    service = request.app.state.retention
    if service.running:
        raise HTTPException(status_code=409, detail="Ya hay una poda en curso")
    run = await service.run_once("manual")
    return _run_out(run)  # type: ignore[return-value]


class RuntimeOut(BaseModel):
    uptime_seconds: int
    ws_clients: int
    ws_dropped_clients: int
    activity_queue_size: int
    activity_queue_max: int
    activity_dropped: int
    event_loop_lag_ms: float
    retention_running: bool


@router.get("/runtime", response_model=RuntimeOut)
async def get_runtime(request: Request, _admin: RequireAdminDep) -> RuntimeOut:
    """Salud del propio proceso MeshSentinel (no de la malla)."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await asyncio.sleep(0)
    lag_ms = round((loop.time() - t0) * 1000, 2)
    writer = request.app.state.activity_log_writer.metrics()
    return RuntimeOut(
        uptime_seconds=int(loop.time() - request.app.state.started_at),
        ws_clients=hub.client_count,
        ws_dropped_clients=hub.dropped_clients,
        activity_queue_size=writer["queue_size"],
        activity_queue_max=writer["queue_max"],
        activity_dropped=writer["dropped"],
        event_loop_lag_ms=lag_ms,
        retention_running=request.app.state.retention.running,
    )


class DigestSendOut(BaseModel):
    delivered: int
    providers: int


class DigestStatusOut(BaseModel):
    last_sent_at: datetime | None


@router.get("/digest", response_model=DigestStatusOut)
async def digest_status(request: Request, _admin: RequireAdminDep) -> DigestStatusOut:
    return DigestStatusOut(last_sent_at=await request.app.state.digest.last_sent_at())


@router.post("/digest/send", response_model=DigestSendOut)
async def digest_send(request: Request, _admin: RequireAdminDep) -> DigestSendOut:
    """Envía el resumen ahora a todas las integraciones habilitadas."""
    delivered, providers = await request.app.state.digest.send_now()
    if providers == 0:
        raise HTTPException(status_code=409, detail="No hay integraciones de notificación habilitadas")
    return DigestSendOut(delivered=delivered, providers=providers)


@router.get("/backup")
async def download_backup(request: Request, _admin: RequireAdminDep) -> FileResponse:
    """Copia lógica completa (JSONL+gzip) para descargar. Contiene hashes de
    contraseña y tokens de integraciones: es un secreto."""
    fd, name = tempfile.mkstemp(prefix="meshsentinel-", suffix=".jsonl.gz")
    os.close(fd)
    path = Path(name)
    try:
        await write_backup(request.app.state.db.session_factory, path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=f"meshsentinel-{stamp}.jsonl.gz",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


# ── Copias programadas (application/backup.py) ───────────────────────────────


class BackupFileOut(BaseModel):
    name: str
    size_bytes: int
    created_at: datetime


class BackupRunOut(BaseModel):
    finished_at: datetime
    duration_seconds: float
    trigger: str
    file: str | None
    size_bytes: int | None
    error: str | None


class BackupStatusOut(BaseModel):
    directory: str
    files: list[BackupFileOut]
    last_run: BackupRunOut | None
    running: bool


@router.get("/backups", response_model=BackupStatusOut)
async def list_backups(request: Request, _admin: RequireAdminDep) -> BackupStatusOut:
    service = request.app.state.backups
    run = service.last_run
    return BackupStatusOut(
        directory=str(service.directory),
        files=[BackupFileOut(name=f.name, size_bytes=f.size_bytes, created_at=f.created_at) for f in service.list_backups()],
        last_run=BackupRunOut(**{k: getattr(run, k) for k in BackupRunOut.model_fields}) if run else None,
        running=service.running,
    )


@router.post("/backups/run", response_model=BackupRunOut)
async def run_backup(request: Request, _admin: RequireAdminDep) -> BackupRunOut:
    """Hace una copia ahora, en el directorio de copias programadas."""
    service = request.app.state.backups
    if service.running:
        raise HTTPException(status_code=409, detail="Ya hay una copia en curso")
    run = await service.run_once("manual")
    return BackupRunOut(**{k: getattr(run, k) for k in BackupRunOut.model_fields})


@router.get("/backups/{name}")
async def download_stored_backup(name: str, request: Request, _admin: RequireAdminDep) -> FileResponse:
    path = request.app.state.backups.path_of(name)  # solo nombres ya listados: sin path traversal
    if path is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, media_type="application/gzip", filename=name)
