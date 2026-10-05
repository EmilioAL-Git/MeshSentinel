"""ADR 0032: pasarelas de solo recepción, primaria designada, orden y
resincronización. El enrutado de operaciones que emiten a la malla debe
ignorar las que no pueden transmitir."""


from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.application.admin.gateway_routing import resolve_gateway, select_gateway_for_node
from noc.application.ingest import IngestService
from noc.domain.nodes.entities import GatewayInfo

from test_gateway_routing import NODE_A, heartbeat, make_event, make_settings, seen


async def _info(session_factory, gateway_id):
    async with session_factory() as session:
        return await SqlGatewayRepository(session).get(gateway_id)


async def test_can_transmit_property():
    assert GatewayInfo(gateway_id="g", status="connected", transport="tcp").can_transmit
    assert not GatewayInfo(gateway_id="g", status="connected", transport="tcp", receive_only=True).can_transmit
    assert not GatewayInfo(gateway_id="g", status="connected", transport="tcp", tx_enabled=False).can_transmit
    # tx_enabled desconocido (None) NO equivale a solo recepción
    assert GatewayInfo(gateway_id="g", status="connected", transport="tcp", tx_enabled=None).can_transmit


async def test_receive_only_gateway_is_skipped_even_with_best_link(session_factory):
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=-9.0, hops=3)
    await seen(ingest, NODE_A, "gw-02", snr=8.0, hops=0)  # mejor enlace
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session:
        await SqlGatewayRepository(session).set_receive_only("gw-02", True)
        await session.commit()
    async with session_factory() as session:
        chosen = await select_gateway_for_node(session, NODE_A, make_settings())
    assert chosen == "gw-01"


async def test_tx_disabled_reported_by_gateway_excludes_it(session_factory):
    """El propio gateway reporta tx_enabled=false (firmware con TX apagado)."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=8.0)
    await ingest.handle_event(
        make_event(
            "gateway.status",
            {"status": "connected", "transport": "tcp", "tx_enabled": False},
            "gw-01",
        )
    )
    assert (await _info(session_factory, "gw-01")).tx_enabled is False
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings())
    assert resolution.gateway_id is None  # única pasarela y no transmite: no enrutable


async def test_forced_receive_only_gateway_is_refused_with_note(session_factory):
    await heartbeat(session_factory, "gw-01")
    async with session_factory() as session:
        await SqlGatewayRepository(session).set_receive_only("gw-01", True)
        await session.commit()
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings(), forced_gateway_id="gw-01")
    assert resolution.gateway_id is None and resolution.source == "forced"
    assert "solo recepción" in resolution.note


async def test_primary_is_exclusive_and_used_as_last_resort(session_factory):
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session:
        repo = SqlGatewayRepository(session)
        await repo.set_primary("gw-01", True)
        await repo.set_primary("gw-02", True)  # quita la marca a gw-01
        await session.commit()
    assert not (await _info(session_factory, "gw-01")).is_primary
    assert (await _info(session_factory, "gw-02")).is_primary
    # nodo sin enlaces ni caché: ninguna pasarela lo ha oído → la primaria
    async with session_factory() as session:
        chosen = await select_gateway_for_node(session, "!0000ffff", make_settings())
    assert chosen == "gw-02"


async def test_primary_not_used_when_not_operational(session_factory):
    await heartbeat(session_factory, "gw-01", status="disconnected")
    async with session_factory() as session:
        await SqlGatewayRepository(session).set_primary("gw-01", True)
        await session.commit()
        chosen = await select_gateway_for_node(session, "!0000ffff", make_settings())
    assert chosen is None


async def test_reorder_defines_listing_order(session_factory):
    for gid in ("gw-a", "gw-b", "gw-c"):
        await heartbeat(session_factory, gid)
    async with session_factory() as session:
        repo = SqlGatewayRepository(session)
        assert [g.gateway_id for g in await repo.list_all()] == ["gw-a", "gw-b", "gw-c"]
        await repo.reorder(["gw-c", "gw-a", "gw-b"])
        await session.commit()
    async with session_factory() as session:
        assert [g.gateway_id for g in await SqlGatewayRepository(session).list_all()] == [
            "gw-c", "gw-a", "gw-b",
        ]
