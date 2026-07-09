"""Batch Engine (M2): coordinación de lotes sobre el pipeline existente.

El motor NO ejecuta nada por sí mismo: crea una AdminOperation por nodo (con
batch_id) y deja que el scheduler/tracker de ADR 0013 hagan todo el trabajo
(cola, rate limit, verify, reintentos, auditoría). Este módulo solo aporta:
- resolución + simulación del alcance (preview sin efectos);
- creación del lote con snapshot congelado;
- control (pausa/reanudación/cancelación de lo no iniciado);
- detección de finalización y cálculo de progreso/ETA.
"""

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.admin_repositories import (
    SqlAdminBatchRepository,
    SqlAdminOperationRepository,
)
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.activity import activity
from noc.application.admin.registry import OPERATIONS, validate_operation
from noc.application.dashboard import ensure_utc
from noc.application.node_filters import NodeFilters, apply_filters
from noc.config import Settings
from noc.domain.admin.entities import TERMINAL_STATUSES, AdminBatch, AdminOperation

logger = logging.getLogger("noc.admin.batch")

FAILURE_STATUSES = ("failed", "timeout", "verify_failed")


# ── Selección de alcance ─────────────────────────────────────────────────────


@dataclass(slots=True)
class BatchScope:
    """Criterios de selección: ids explícitos y/o filtros/grupo/favoritos.
    Los criterios se combinan en unión (ids) ∪ (resultado de filtros)."""

    node_ids: list[str] = field(default_factory=list)
    filters: NodeFilters | None = None

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.node_ids:
            out["explicit_node_ids"] = len(self.node_ids)
        if self.filters is not None and not self.filters.is_empty:
            out["filters"] = {
                k: v for k, v in asdict(self.filters).items() if v not in (None, False, "")
            }
        return out


@dataclass(slots=True)
class PlannedOperation:
    """Operación concreta de un lote heterogéneo (M3: perfiles). El motor no
    interpreta los params: ya llegan validados por el registro."""

    node_id: str
    gateway_id: str
    operation_type: str
    params: dict[str, Any]


@dataclass(slots=True)
class NodePreview:
    node_id: str
    display_name: str
    eligible: bool
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BatchPreview:
    operation_type: str
    params: dict[str, Any]
    total_selected: int
    eligible: list[NodePreview]
    excluded: list[NodePreview]
    requires_verification: bool
    estimated_seconds: int
    scope_description: dict[str, Any]


class BatchService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    # ── Simulación (sin efectos) ─────────────────────────────────────────────

    async def preview(
        self, operation_type: str, params: dict[str, Any], scope: BatchScope
    ) -> BatchPreview:
        spec = OPERATIONS.get(operation_type)
        if spec is None:
            raise ValueError(f"Unknown operation_type: {operation_type}")
        if not spec.allow_bulk:
            raise ValueError(f"Operation '{operation_type}' does not allow bulk execution")
        normalized = validate_operation(operation_type, params)

        async with self._session_factory() as session:
            summaries = await SqlNodeRepository(session).list_summaries()

        by_id = {s.node.node_id: s for s in summaries}
        selected_ids: set[str] = set(scope.node_ids)
        if scope.filters is not None:
            filtered = apply_filters(
                summaries, scope.filters, self._settings.node_offline_after_seconds
            )
            selected_ids |= {s.node.node_id for s in filtered}

        eligible: list[NodePreview] = []
        excluded: list[NodePreview] = []
        threshold = self._settings.node_offline_after_seconds
        for node_id in sorted(selected_ids):
            summary = by_id.get(node_id)
            if summary is None:
                excluded.append(
                    NodePreview(node_id, node_id, False, blockers=["desconocido en el registry"])
                )
                continue
            node = summary.node
            name = node.long_name or node.short_name or node_id
            preview = NodePreview(node_id, name, True)
            if not node.gateway_id:
                preview.blockers.append("sin pasarela conocida (no enrutable)")
            if not node.is_online(threshold):
                preview.warnings.append("sin conexión reciente: probable timeout")
            if node.is_ignored:
                preview.warnings.append("marcado como ignorado")
            if preview.blockers:
                preview.eligible = False
                excluded.append(preview)
            else:
                eligible.append(preview)

        return BatchPreview(
            operation_type=operation_type,
            params=normalized,
            total_selected=len(selected_ids),
            eligible=eligible,
            excluded=excluded,
            requires_verification=spec.kind == "set",
            estimated_seconds=self.estimate_seconds(len(eligible)),
            scope_description=scope.describe(),
        )

    def estimate_seconds(self, operations: int) -> int:
        """Estimación honesta por presupuesto de malla: el rate limit global
        domina cualquier otro factor (diseño §4.4)."""
        if operations <= 0:
            return 0
        per_minute = max(self._settings.admin_rate_limit_per_minute, 1)
        return max(1, math.ceil(operations * 60 / per_minute))

    # ── Creación ─────────────────────────────────────────────────────────────

    async def create(
        self,
        name: str,
        operation_type: str,
        params: dict[str, Any],
        node_ids: list[str],
        scope_description: dict[str, Any] | None,
        created_by: str = "admin",
    ) -> AdminBatch:
        spec = OPERATIONS.get(operation_type)
        if spec is None:
            raise ValueError(f"Unknown operation_type: {operation_type}")
        if not spec.allow_bulk:
            raise ValueError(f"Operation '{operation_type}' does not allow bulk execution")
        if not node_ids:
            raise ValueError("Batch requires at least one node")
        normalized = validate_operation(operation_type, params)

        async with self._session_factory() as session:
            node_repo = SqlNodeRepository(session)
            planned: list[PlannedOperation] = []
            for node_id in dict.fromkeys(node_ids):  # dedupe conservando orden
                node = await node_repo.get(node_id)
                if node is None:
                    raise ValueError(f"Node {node_id} not found in registry")
                if not node.gateway_id:
                    raise ValueError(f"Node {node_id} has no known gateway (run preview first)")
                planned.append(
                    PlannedOperation(node_id, node.gateway_id, operation_type, normalized)
                )

        return await self.create_planned(
            name, operation_type, normalized, planned, scope_description, created_by
        )

    async def create_planned(
        self,
        name: str,
        operation_type: str,
        params: dict[str, Any],
        planned: list[PlannedOperation],
        scope_description: dict[str, Any] | None,
        created_by: str = "admin",
    ) -> AdminBatch:
        """Crea un lote a partir de operaciones ya resueltas y validadas.

        Es la única puerta de creación de lotes: `create` (M2, operación
        uniforme) y la sincronización de perfiles (M3, operaciones por nodo)
        pasan por aquí. El pipeline de ADR 0013 no distingue unos de otros.
        """
        if not planned:
            raise ValueError("Batch requires at least one operation")

        now = datetime.now(timezone.utc)
        async with self._session_factory() as session, session.begin():
            batch = await SqlAdminBatchRepository(session).create(
                AdminBatch(
                    name=name,
                    operation_type=operation_type,
                    params=params,
                    node_ids=list(dict.fromkeys(p.node_id for p in planned)),
                    scope_description=scope_description,
                    status="running",
                    created_by=created_by,
                    created_at=now,
                    started_at=now,
                )
            )
            op_repo = SqlAdminOperationRepository(session)
            for op in planned:
                await op_repo.create(
                    AdminOperation(
                        batch_id=batch.id,
                        target_node_id=op.node_id,
                        gateway_id=op.gateway_id,
                        operation_type=op.operation_type,
                        params=op.params,
                        timeout_seconds=self._settings.admin_default_timeout_seconds,
                        max_attempts=self._settings.admin_max_attempts,
                        created_by=created_by,
                    )
                )
        logger.info(
            "batch.created id=%s name=%r ops=%d type=%s", batch.id, name, len(planned), operation_type
        )
        await activity.batch(batch, "created")
        return batch

    # ── Control ──────────────────────────────────────────────────────────────

    async def pause(self, batch_id: int) -> AdminBatch | None:
        async with self._session_factory() as session, session.begin():
            repo = SqlAdminBatchRepository(session)
            batch = await repo.get(batch_id)
            if batch is None or batch.status != "running":
                return None
            batch = await repo.update_fields(batch_id, {"status": "paused"})
        logger.info("batch.paused id=%s", batch_id)
        assert batch is not None
        await activity.batch(batch, "paused")
        return batch

    async def resume(self, batch_id: int) -> AdminBatch | None:
        async with self._session_factory() as session, session.begin():
            repo = SqlAdminBatchRepository(session)
            batch = await repo.get(batch_id)
            if batch is None or batch.status != "paused":
                return None
            batch = await repo.update_fields(batch_id, {"status": "running"})
        logger.info("batch.resumed id=%s", batch_id)
        assert batch is not None
        await activity.batch(batch, "resumed")
        return batch

    async def cancel(self, batch_id: int) -> AdminBatch | None:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session, session.begin():
            repo = SqlAdminBatchRepository(session)
            batch = await repo.get(batch_id)
            if batch is None or batch.is_terminal:
                return None
            cancelled = await repo.cancel_pending_operations(batch_id, now)
            # Las running siguen su curso; el lote queda cancelled y se cierra
            # del todo cuando terminen (maybe_complete no lo tocará: terminal)
            changes: dict[str, Any] = {"status": "cancelled"}
            if not await repo.has_open_operations(batch_id):
                changes["finished_at"] = now
            batch = await repo.update_fields(batch_id, changes)
        logger.info("batch.cancelled id=%s pending_cancelled=%d", batch_id, cancelled)
        assert batch is not None
        await activity.batch(batch, "cancelled", cancelled_pending=cancelled)
        return batch

    # ── Finalización y progreso ──────────────────────────────────────────────

    async def maybe_complete(self, session: AsyncSession, batch_id: int) -> None:
        """Llamado por el tracker tras cada transición terminal de una
        operación con batch_id (misma transacción)."""
        repo = SqlAdminBatchRepository(session)
        batch = await repo.get(batch_id)
        if batch is None or batch.is_terminal:
            # cancelled: solo cerramos finished_at cuando las running acaben
            if batch is not None and batch.status == "cancelled" and batch.finished_at is None:
                if not await repo.has_open_operations(batch_id):
                    await repo.update_fields(
                        batch_id, {"finished_at": datetime.now(timezone.utc)}
                    )
            return
        if await repo.has_open_operations(batch_id):
            return
        counts = await repo.status_counts(batch_id)
        failures = sum(counts.get(s, 0) for s in FAILURE_STATUSES)
        status = "completed_with_errors" if failures else "completed"
        updated = await repo.update_fields(
            batch_id, {"status": status, "finished_at": datetime.now(timezone.utc)}
        )
        logger.info("batch.%s id=%s counts=%s", status, batch_id, counts)
        if updated is not None:
            await activity.batch(updated, status, counts=counts)

    async def progress(self, session: AsyncSession, batch: AdminBatch) -> dict[str, Any]:
        repo = SqlAdminBatchRepository(session)
        counts = await repo.status_counts(batch.id or 0)
        total = sum(counts.values())
        done = sum(counts.get(s, 0) for s in TERMINAL_STATUSES)
        running_op = await repo.running_operation(batch.id or 0)

        now = datetime.now(timezone.utc)
        elapsed = (
            int((now - ensure_utc(batch.started_at)).total_seconds()) if batch.started_at else 0
        )
        finished_elapsed = (
            int((ensure_utc(batch.finished_at) - ensure_utc(batch.started_at)).total_seconds())
            if batch.finished_at and batch.started_at
            else None
        )
        remaining = counts.get("pending", 0) + counts.get("queued", 0) + counts.get("running", 0)
        rate_per_minute = (done / elapsed * 60) if elapsed > 0 and done > 0 else None
        if batch.is_terminal:
            eta_seconds = 0
        elif rate_per_minute:
            eta_seconds = int(remaining * 60 / rate_per_minute)
        else:
            eta_seconds = self.estimate_seconds(remaining)

        return {
            "counts": counts,
            "total": total,
            "done": done,
            "percent": round(100 * done / total, 1) if total else 100.0,
            "current_node_id": running_op.target_node_id if running_op else None,
            "rate_per_minute": round(rate_per_minute, 2) if rate_per_minute else None,
            "eta_seconds": eta_seconds,
            "elapsed_seconds": finished_elapsed if finished_elapsed is not None else elapsed,
        }
