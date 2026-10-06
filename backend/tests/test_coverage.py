from datetime import datetime, timedelta, timezone

from noc.application.ingest import IngestService
from noc.adapters.persistence.repositories import SqlCoverageRepository
from test_stats import make_event

NOW = datetime.now(timezone.utc)


async def _node_seen(ingest, hops: int | None):
    await ingest.handle_event(make_event("gateway.status", {"status": "connected", "transport": "simulated"}))
    await ingest.handle_event(
        make_event("node.seen", {"node_id": "!00000001", "short_name": "N1", "snr": 6.0, "hops_away": hops})
    )


async def _position(ingest, **extra):
    payload = {"node_id": "!00000001", "latitude": 40.1234, "longitude": -2.5678, "snr": 6.0, "rssi": -80, **extra}
    await ingest.handle_event(make_event("position.updated", payload))


async def _cells(session_factory):
    async with session_factory() as s:
        return await SqlCoverageRepository(s).cells(NOW - timedelta(days=1))


async def test_direct_position_with_snr_is_recorded(session_factory):
    ingest = IngestService(session_factory)
    await _node_seen(ingest, 0)
    await _position(ingest)
    await _position(ingest, snr=2.0)
    cells = await _cells(session_factory)
    assert len(cells) == 1 and cells[0]["receptions"] == 2 and cells[0]["avg_snr"] == 4.0


async def test_relayed_or_fuzzy_or_snrless_positions_are_not_measured(session_factory):
    ingest = IngestService(session_factory)
    await _node_seen(ingest, 3)  # a 3 saltos: no mide cobertura directa
    await _position(ingest)
    assert await _cells(session_factory) == []

    ingest2 = IngestService(session_factory)
    await _node_seen(ingest2, 0)
    await _position(ingest2, precision_bits=11)  # difuminada a km
    await _position(ingest2, snr=None)
    assert await _cells(session_factory) == []
