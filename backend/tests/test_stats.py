import uuid
from datetime import datetime, timezone

from noc.application.ingest import IngestService
from noc.application.stats import StatsService
from noc.config import Settings


def make_event(event_type: str, payload: dict, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


def make_settings(**overrides) -> Settings:
    overrides.setdefault("stats_cache_seconds", 0)
    return Settings(_env_file=None, **overrides)


async def seed(session_factory) -> None:
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("gateway.status", {"status": "connected", "transport": "simulated"}))

    # El más transmisor / canal más saturado / más uptime / batería más baja
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000001", "short_name": "TX", "snr": 4.0}))
    await ingest.handle_event(
        make_event(
            "telemetry.received",
            {
                "node_id": "!00000001",
                "kind": "device",
                "battery_level": 8,
                "channel_utilization": 45.0,
                "air_util_tx": 12.5,
                "uptime_seconds": 500_000,
            },
        )
    )

    # El más caliente + presión (environment) + mejor SNR
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000002", "short_name": "HOT", "snr": 9.0}))
    await ingest.handle_event(
        make_event(
            "telemetry.received",
            {
                "node_id": "!00000002",
                "kind": "environment",
                "temperature_c": 41.0,
                "relative_humidity": 30.0,
                "barometric_pressure_hpa": 1012.0,
            },
        )
    )

    # El más frío + peor SNR + nodo con alimentación externa (excluido de batería baja)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000003", "short_name": "COLD", "snr": -20.0}))
    await ingest.handle_event(
        make_event(
            "telemetry.received",
            {"node_id": "!00000003", "kind": "environment", "temperature_c": -3.0},
        )
    )
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000003", "kind": "device", "battery_level": 101})
    )

    # El más alto (posición)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000004", "short_name": "ALTO"}))
    await ingest.handle_event(
        make_event("position.updated", {"node_id": "!00000004", "latitude": 1.0, "longitude": 1.0, "altitude_m": 3500})
    )

    # Ignorado: no debe colar ningún récord aunque tenga valores extremos
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000005", "short_name": "IGN", "snr": 99.0}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000005", "kind": "device", "air_util_tx": 99.0})
    )


async def ignore_node(session_factory, node_id: str) -> None:
    from noc.adapters.persistence.repositories import SqlNodeRepository

    async with session_factory() as session:
        await SqlNodeRepository(session).set_flag(node_id, "is_ignored", True)
        await session.commit()


async def test_stats_records(session_factory):
    await seed(session_factory)
    await ignore_node(session_factory, "!00000005")

    service = StatsService(session_factory, make_settings())
    s = await service.get_summary()

    by_key = {r.key: r for r in s.records}
    assert s.nodes_total == 4  # el ignorado no cuenta
    assert by_key["air_tx"].node_id == "!00000001"
    assert by_key["air_tx"].value == 12.5
    assert by_key["channel_util"].node_id == "!00000001"
    assert by_key["uptime"].node_id == "!00000001"
    assert by_key["low_battery"].node_id == "!00000001"  # el 101 (externo) queda fuera
    assert by_key["hottest"].node_id == "!00000002"
    assert by_key["coldest"].node_id == "!00000003"
    assert by_key["best_snr"].node_id == "!00000002"
    assert by_key["worst_snr"].node_id == "!00000003"
    assert by_key["altitude"].node_id == "!00000004"
    assert by_key["pressure"].node_id == "!00000002"
    assert "humid" in by_key and by_key["humid"].node_id == "!00000002"
    assert "veteran" in by_key and "rookie" in by_key


async def test_stats_cache(session_factory):
    await seed(session_factory)
    service = StatsService(session_factory, make_settings(stats_cache_seconds=60))
    first = await service.get_summary()
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event(
            "telemetry.received",
            {"node_id": "!00000001", "kind": "device", "air_util_tx": 200.0},
        )
    )
    cached = await service.get_summary()
    assert cached is first  # dentro del TTL no se recomputa


async def test_stats_ranking(session_factory):
    await seed(session_factory)
    await ignore_node(session_factory, "!00000005")

    service = StatsService(session_factory, make_settings())
    s = await service.get_summary()

    ranking = await service.get_ranking("best_snr")
    assert ranking is not None
    assert [r.node_id for r in ranking] == ["!00000002", "!00000001", "!00000003"]
    assert [r.value for r in ranking] == [9.0, 4.0, -20.0]
    # La cabecera del ranking es siempre el récord del resumen para esa clave.
    by_key = {r.key: r for r in s.records}
    assert ranking[0] == by_key["best_snr"]

    assert await service.get_ranking("no-existe") is None


async def test_stats_empty_network(session_factory):
    service = StatsService(session_factory, make_settings())
    s = await service.get_summary()
    assert s.nodes_total == 0
    assert s.records == []
    assert s.network_age_days is None


async def test_stats_window_excludes_old_samples(session_factory):
    from datetime import timedelta

    from noc.adapters.persistence.repositories import SqlTelemetryRepository
    from noc.domain.nodes.entities import Telemetry

    await seed(session_factory)
    await ignore_node(session_factory, "!00000005")
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    async with session_factory() as session:
        await SqlTelemetryRepository(session).add(
            Telemetry(node_id="!00000002", kind="device", air_util_tx=77.0, received_at=old)
        )
        await session.commit()

    service = StatsService(session_factory, make_settings())
    day = {r.key: r for r in (await service.get_summary(24)).records}
    week = {r.key: r for r in (await service.get_summary(168)).records}
    assert day["air_tx"].node_id == "!00000001"  # la muestra de hace 30 h queda fuera
    assert week["air_tx"].node_id == "!00000002" and week["air_tx"].value == 77.0
    assert (await service.get_summary(9999)).window_hours == 168  # tope: 1 semana
