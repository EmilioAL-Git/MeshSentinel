"""Persistencia de trazas de la red real (ADR 0031). Append-only."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import TraceHopModel, TraceModel
from noc.application.traces import TraceRecord

# Ventana en la que una traza ACTIVA (resultado de la operación) y el paquete
# pasivo que la originó se consideran la MISMA traza física. El orden de
# llegada de ambos no está garantizado, así que se fusionan en los dos sentidos.
MERGE_WINDOW = timedelta(seconds=90)


@dataclass(slots=True)
class TraceEdge:
    """Arista dirigida agregada del grafo acumulado."""

    src_id: str
    dst_id: str
    observations: int
    active_observations: int
    avg_snr: float | None
    min_snr: float | None
    max_snr: float | None
    last_snr: float | None
    first_seen: datetime
    last_seen: datetime


class SqlTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, trace: TraceRecord) -> tuple[int, bool]:
        """Guarda la traza; devuelve (id, creada). Si ya existe la misma traza
        física por la otra vía (activa<->pasiva) la fusiona en vez de duplicar."""
        merged = await self._merge_existing(trace)
        if merged is not None:
            return merged, False
        row = TraceModel(
            gateway_id=trace.gateway_id,
            origin_id=trace.origin_id,
            target_id=trace.target_id,
            source=trace.source,
            kind=trace.kind,
            reached=trace.reached,
            route=trace.route,
            route_back=trace.route_back,
            snr_towards=trace.snr_towards,
            snr_back=trace.snr_back,
            operation_id=trace.operation_id,
            from_packet=trace.from_packet,
            received_at=trace.received_at,
        )
        self._session.add(row)
        await self._session.flush()
        for hop in trace.hops:
            self._session.add(
                TraceHopModel(
                    trace_id=row.id,
                    src_id=hop.src,
                    dst_id=hop.dst,
                    snr=hop.snr,
                    direction=hop.direction,
                    position=hop.position,
                    received_at=trace.received_at,
                )
            )
        await self._session.flush()
        return row.id, True

    async def _merge_existing(self, trace: TraceRecord) -> int | None:
        lo, hi = trace.received_at - MERGE_WINDOW, trace.received_at + MERGE_WINDOW
        same_pair = (
            TraceModel.gateway_id == trace.gateway_id,
            TraceModel.origin_id == trace.origin_id,
            TraceModel.target_id == trace.target_id,
            TraceModel.received_at >= lo,
            TraceModel.received_at <= hi,
        )
        if trace.operation_id is not None:
            # Resultado activo: ¿ya llegó su paquete suelto?
            stmt = select(TraceModel).where(
                *same_pair, TraceModel.from_packet.is_(True), TraceModel.operation_id.is_(None)
            )
            if trace.reached:
                row = (await self._session.scalars(stmt.limit(1))).first()
                if row is not None:
                    row.operation_id = trace.operation_id
                    row.source = "active"
                    await self._session.flush()
                    return row.id
            return None
        if not trace.from_packet:
            return None
        # Paquete suelto: ¿ya se registró el resultado de la operación que lo causó?
        row = (
            await self._session.scalars(
                select(TraceModel)
                .where(
                    *same_pair,
                    TraceModel.from_packet.is_(False),
                    TraceModel.operation_id.is_not(None),
                    TraceModel.reached.is_(True),
                )
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        row.from_packet = True
        await self._session.flush()
        return row.id

    async def list_recent(
        self,
        *,
        node_id: str | None = None,
        operation_id: int | None = None,
        gateway_id: str | None = None,
        source: str | None = None,
        reached: bool | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[TraceModel]:
        stmt = select(TraceModel).order_by(TraceModel.received_at.desc(), TraceModel.id.desc())
        if node_id is not None:
            stmt = stmt.where(
                (TraceModel.origin_id == node_id)
                | (TraceModel.target_id == node_id)
            )
        if operation_id is not None:
            stmt = stmt.where(TraceModel.operation_id == operation_id)
        if gateway_id:
            stmt = stmt.where(TraceModel.gateway_id == gateway_id)
        if source:
            stmt = stmt.where(TraceModel.source == source)
        if reached is not None:
            stmt = stmt.where(TraceModel.reached.is_(reached))
        if since is not None:
            stmt = stmt.where(TraceModel.received_at >= since)
        return list((await self._session.scalars(stmt.limit(limit))).all())

    async def get(self, trace_id: int) -> TraceModel | None:
        return await self._session.get(TraceModel, trace_id)

    async def exists_near(
        self, gateway_id: str | None, origin_id: str, target_id: str, at: datetime
    ) -> bool:
        """¿Ya hay una traza (de cualquier origen) de ese par en ±MERGE_WINDOW?"""
        row = await self._session.scalar(
            select(TraceModel.id)
            .where(
                TraceModel.gateway_id == gateway_id,
                TraceModel.origin_id == origin_id,
                TraceModel.target_id == target_id,
                TraceModel.received_at >= at - MERGE_WINDOW,
                TraceModel.received_at <= at + MERGE_WINDOW,
            )
            .limit(1)
        )
        return row is not None

    async def graph(self, *, since: datetime | None = None) -> list[TraceEdge]:
        """Aristas dirigidas agregadas: nº de observaciones, SNR medio/mín/máx,
        último SNR y primera/última vez vista. Dos consultas (agregado + último
        valor por ventana) combinadas en Python: ambas portables PG/SQLite."""
        criteria: list[Any] = []
        if since is not None:
            criteria.append(TraceHopModel.received_at >= since)

        agg = await self._session.execute(
            select(
                TraceHopModel.src_id,
                TraceHopModel.dst_id,
                func.count(TraceHopModel.id),
                func.avg(TraceHopModel.snr),
                func.min(TraceHopModel.snr),
                func.max(TraceHopModel.snr),
                func.min(TraceHopModel.received_at),
                func.max(TraceHopModel.received_at),
            )
            .where(*criteria)
            .group_by(TraceHopModel.src_id, TraceHopModel.dst_id)
        )
        active = dict(
            (
                (r[0], r[1]),
                r[2],
            )
            for r in (
                await self._session.execute(
                    select(
                        TraceHopModel.src_id,
                        TraceHopModel.dst_id,
                        func.sum(case((TraceModel.source == "active", 1), else_=0)),
                    )
                    .join(TraceModel, TraceModel.id == TraceHopModel.trace_id)
                    .where(*criteria)
                    .group_by(TraceHopModel.src_id, TraceHopModel.dst_id)
                )
            ).all()
        )
        rn = (
            func.row_number()
            .over(
                partition_by=(TraceHopModel.src_id, TraceHopModel.dst_id),
                order_by=(TraceHopModel.received_at.desc(), TraceHopModel.id.desc()),
            )
            .label("rn")
        )
        sub = select(TraceHopModel.src_id, TraceHopModel.dst_id, TraceHopModel.snr, rn).where(*criteria).subquery()
        last = {
            (r[0], r[1]): r[2]
            for r in (
                await self._session.execute(
                    select(sub.c.src_id, sub.c.dst_id, sub.c.snr).where(sub.c.rn == 1)
                )
            ).all()
        }
        return [
            TraceEdge(
                src_id=src,
                dst_id=dst,
                observations=int(count),
                active_observations=int(active.get((src, dst)) or 0),
                avg_snr=None if avg is None else round(float(avg), 2),
                min_snr=mn,
                max_snr=mx,
                last_snr=last.get((src, dst)),
                first_seen=first,
                last_seen=seen,
            )
            for src, dst, count, avg, mn, mx, first, seen in agg.all()
        ]
