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
