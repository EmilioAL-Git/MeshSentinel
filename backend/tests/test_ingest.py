import uuid
from datetime import datetime, timedelta, timezone

from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNeighborRepository,
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.application.ingest import IngestService

NODE_A = "!a1b2c3d4"
NODE_B = "!deadbeef"


def make_event(event_type: str, payload: dict, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


async def test_node_seen_creates_and_updates(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODE_A, "short_name": "AAA", "hw_model": "TBEAM"})
    )
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_A, "long_name": "Nodo A"}))

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
    assert node is not None
    assert node.short_name == "AAA"  # no se borra al llegar un sighting parcial
    assert node.long_name == "Nodo A"
    assert node.hw_model == "TBEAM"
    assert node.gateway_id == "gw-test"


async def test_position_and_telemetry_are_appended_and_touch_last_seen(session_factory):
    ingest = IngestService(session_factory)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    t1 = datetime.now(timezone.utc)

    await ingest.handle_event(
        make_event("position.updated", {"node_id": NODE_A, "latitude": 40.0, "longitude": -3.0}, t0)
    )
    await ingest.handle_event(
        make_event("position.updated", {"node_id": NODE_A, "latitude": 41.0, "longitude": -3.5}, t1)
    )
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": NODE_A, "kind": "device", "battery_level": 77}, t1)
    )

    async with session_factory() as session:
        # El nodo se auto-crea aunque nunca llegara node.seen
        node = await SqlNodeRepository(session).get(NODE_A)
        assert node is not None
        positions = await SqlPositionRepository(session).list_for_node(NODE_A, limit=10)
        telemetry = await SqlTelemetryRepository(session).list_for_node(NODE_A, limit=10, kind="device")

    assert len(positions) == 2  # append-only: nunca se sobreescribe
    assert positions[0].latitude == 41.0  # orden descendente por received_at
    assert telemetry[0].battery_level == 77
    assert node.is_online(threshold_seconds=900)


async def test_neighbors_seen_persists_append_only_links(session_factory):
    ingest = IngestService(session_factory)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    t1 = datetime.now(timezone.utc)

    await ingest.handle_event(
        make_event(
            "neighbors.seen",
            {"node_id": NODE_A, "neighbors": [{"neighbor_id": NODE_B, "snr": 4.5}]},
            t0,
        )
    )
    await ingest.handle_event(
        make_event(
            "neighbors.seen",
            {"node_id": NODE_A, "neighbors": [{"neighbor_id": NODE_B, "snr": 6.0}]},
            t1,
        )
    )

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
        links = await SqlNeighborRepository(session).list_for_node(NODE_A, limit=10)
        latest_for_node = await SqlNeighborRepository(session).list_latest_for_node(NODE_A)
        latest_network = await SqlNeighborRepository(session).list_latest_network()
        windowed = await SqlNeighborRepository(session).list_latest_network(
            since=datetime.now(timezone.utc) - timedelta(minutes=1)
        )

    assert node is not None  # touch_last_seen auto-crea el nodo, como position/telemetry
    assert len(links) == 2  # append-only: nunca se sobreescribe
    assert links[0].snr == 6.0  # orden descendente por received_at
    # Vecindario actual: un solo enlace por vecino, el más reciente (API /neighbors)
    assert len(latest_for_node) == 1
    assert latest_for_node[0].snr == 6.0
    assert len(latest_network) == 1  # un solo par (node_id, neighbor_id): solo el más reciente
    assert latest_network[0].snr == 6.0
    # Ventana temporal (/topology?since_hours): el par de t0 (5 min atrás)
    # solo sobrevive porque su ÚLTIMO enlace (t1) cae dentro de la ventana
    assert len(windowed) == 1


async def test_list_summaries_returns_latest_values(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_A, "short_name": "AAA"}))
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_B, "short_name": "BBB"}))
    await ingest.handle_event(
        make_event("position.updated", {"node_id": NODE_A, "latitude": 40.0, "longitude": -3.0})
    )
    await ingest.handle_event(
        make_event("position.updated", {"node_id": NODE_A, "latitude": 42.0, "longitude": -3.7})
    )
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": NODE_A, "kind": "device", "battery_level": 55})
    )

    async with session_factory() as session:
        summaries = await SqlNodeRepository(session).list_summaries()

    by_id = {s.node.node_id: s for s in summaries}
    assert set(by_id) == {NODE_A, NODE_B}
    assert by_id[NODE_A].last_position is not None
    assert by_id[NODE_A].last_position.latitude == 42.0
    assert by_id[NODE_A].last_device_telemetry.battery_level == 55
    assert by_id[NODE_B].last_position is None


async def test_gateway_status_upsert(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event("gateway.status", {"status": "connected", "transport": "simulated"})
    )
    await ingest.handle_event(
        make_event("gateway.status", {"status": "disconnected", "transport": "simulated"})
    )
    async with session_factory() as session:
        gateways = await SqlGatewayRepository(session).list_all()
    assert len(gateways) == 1
    assert gateways[0].status == "disconnected"


async def test_unsupported_schema_version_is_ignored(session_factory):
    ingest = IngestService(session_factory)
    event = make_event("node.seen", {"node_id": NODE_A})
    event["schema_version"] = 99
    await ingest.handle_event(event)
    async with session_factory() as session:
        assert await SqlNodeRepository(session).get(NODE_A) is None
