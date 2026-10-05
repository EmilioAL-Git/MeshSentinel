"""Importación única de los traceroutes anteriores a ADR 0031.

Hasta entonces solo vivían como entradas TRACEROUTE_APP del Registro. Es
idempotente: una entrada se omite si ya hay una traza de ese par en ±90 s
(por eso repetir la importación no duplica nada)."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.activity_repositories import SqlActivityLogRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.adapters.persistence.trace_repository import SqlTraceRepository
from noc.application.traces import trace_from_legacy_activity

PAGE = 500


def _ts(env: dict[str, Any]) -> datetime:
    raw = env.get("timestamp")
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def import_legacy_traces(session: AsyncSession) -> dict[str, int]:
    activity = SqlActivityLogRepository(session)
    traces = SqlTraceRepository(session)
    gateways = SqlGatewayRepository(session)
    local_of: dict[str | None, str | None] = {}
    stats = {"scanned": 0, "imported": 0, "skipped": 0}
    before: int | None = None
    while True:
        page = await activity.list_recent(PAGE, before_id=before, internal_type="TRACEROUTE_APP")
        if not page:
            break
        for env in page:
            stats["scanned"] += 1
            gw = env.get("gateway_id")
            if gw not in local_of:
                info = await gateways.get(gw) if gw else None
                local_of[gw] = info.local_node_id if info else None
            at = _ts(env)
            raw = (env.get("payload") or {}).get("raw") or {}
            trace = trace_from_legacy_activity(raw, gateway_id=gw, local_node_id=local_of[gw], received_at=at)
            if trace is None or await traces.exists_near(gw, trace.origin_id, trace.target_id, at):
                stats["skipped"] += 1
                continue
            await traces.record(trace)
            stats["imported"] += 1
        last = page[-1].get("log_id")
        if len(page) < PAGE or not isinstance(last, int):
            break
        before = last
    return stats
