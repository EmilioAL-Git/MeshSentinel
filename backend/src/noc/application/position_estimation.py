"""Estimador periódico de posiciones sin GPS (ADR 0035): bucle horario que
recalcula `estimated_positions` con la función pura `compute_estimates`."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.models import EstimatedPositionModel
from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNeighborRepository,
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
)
from noc.adapters.persistence.trace_repository import SqlTraceRepository
from noc.application.position_estimate import Estimate, compute_estimates
from noc.application.rf_graph import build_rf_edges

logger = logging.getLogger("noc.position_estimation")

STARTUP_DELAY_SECONDS = 300
INTERVAL_SECONDS = 3600
WINDOW = timedelta(hours=48)


class PositionEstimationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> int:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            summaries = await SqlNodeRepository(session).list_summaries()
            links = await SqlNodeGatewayLinkRepository(session).list_all()
            gateways = await SqlGatewayRepository(session).list_all()
            neighbors = await SqlNeighborRepository(session).list_latest_network(since=now - WINDOW)
            traces = [
                (e.src_id, e.dst_id, e.avg_snr, e.last_seen)
                for e in await SqlTraceRepository(session).graph(since=now - WINDOW)
            ]
        estimates = compute_estimates(summaries, links, gateways, build_rf_edges(neighbors, traces), now)
        async with self._session_factory() as session, session.begin():
            await self._replace(session, estimates, now)
        logger.info("position estimates: %d nodes", len(estimates))
        return len(estimates)

    @staticmethod
    async def _replace(session: AsyncSession, estimates: dict[str, Estimate], now: datetime) -> None:
        existing = {r.node_id: r for r in (await session.scalars(select(EstimatedPositionModel))).all()}
        stale = [nid for nid in existing if nid not in estimates]
        if stale:
            await session.execute(delete(EstimatedPositionModel).where(EstimatedPositionModel.node_id.in_(stale)))
        for nid, e in estimates.items():
            row = existing.get(nid)
            if row is None:
                session.add(
                    EstimatedPositionModel(
                        node_id=nid, latitude=e.latitude, longitude=e.longitude,
                        radius_m=e.radius_m, anchors=e.anchors, computed_at=now,
                    )
                )
            else:
                row.latitude, row.longitude = e.latitude, e.longitude
                row.radius_m, row.anchors, row.computed_at = e.radius_m, e.anchors, now

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="position-estimation")

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
                await self.run_once()
            except Exception:
                logger.exception("position estimation pass failed")
            await asyncio.sleep(INTERVAL_SECONDS)
