"""M6.1: node_gateway_links, caché derivada en `nodes` y selección de pasarela primaria.

Ver docs/design/m6-multi-gateway.md §1/§3/§6. Con una única pasarela, todo
esto debe ser indistinguible del comportamiento anterior a M6.1 (criterio de
aceptación explícito del usuario).
"""

import uuid
from datetime import datetime, timedelta, timezone

from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
)
from noc.application.gateway_link_selection import GatewayLinkCandidate, select_primary_link
from noc.application.ingest import IngestService

NODE_A = "!a1b2c3d4"


def make_event(event_type: str, payload: dict, gateway_id: str = "gw-test", ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


# ── Función pura de selección (sin infraestructura) ──────────────────────────


def _candidate(gateway_id: str, **kwargs) -> GatewayLinkCandidate:
    base = dict(last_heard_at=datetime.now(timezone.utc), priority=0, hops_away=None, snr=None, rssi=None)
    base.update(kwargs)
    return GatewayLinkCandidate(gateway_id=gateway_id, **base)


def test_select_primary_link_no_candidates_returns_none():
    assert select_primary_link([]) is None


def test_select_primary_link_single_candidate_is_noop():
    only = _candidate("gw-a", hops_away=5, snr=-3.0, rssi=-110)
    assert select_primary_link([only]) is only


def test_select_primary_link_prefers_manual_priority_over_everything_else():
    worse_signal_but_priority = _candidate("gw-a", priority=10, hops_away=5, snr=-10.0, rssi=-120)
    better_signal_no_priority = _candidate("gw-b", priority=0, hops_away=0, snr=10.0, rssi=-40)
    winner = select_primary_link([better_signal_no_priority, worse_signal_but_priority])
    assert winner.gateway_id == "gw-a"


def test_select_primary_link_prefers_fewer_hops_when_priority_ties():
    far = _candidate("gw-far", hops_away=3, snr=5.0, rssi=-50)
    near = _candidate("gw-near", hops_away=1, snr=-5.0, rssi=-90)
    winner = select_primary_link([far, near])
    assert winner.gateway_id == "gw-near"


def test_select_primary_link_prefers_better_snr_when_hops_tie():
    weak = _candidate("gw-weak", hops_away=2, snr=-8.0, rssi=-40)
    strong = _candidate("gw-strong", hops_away=2, snr=6.0, rssi=-95)
    winner = select_primary_link([weak, strong])
    assert winner.gateway_id == "gw-strong"


def test_select_primary_link_prefers_better_rssi_when_snr_ties():
    weak = _candidate("gw-weak", hops_away=1, snr=4.0, rssi=-100)
    strong = _candidate("gw-strong", hops_away=1, snr=4.0, rssi=-40)
    winner = select_primary_link([weak, strong])
    assert winner.gateway_id == "gw-strong"


def test_select_primary_link_recency_is_last_tiebreak():
    now = datetime.now(timezone.utc)
    older = _candidate("gw-old", hops_away=1, snr=4.0, rssi=-40, last_heard_at=now - timedelta(minutes=5))
    newer = _candidate("gw-new", hops_away=1, snr=4.0, rssi=-40, last_heard_at=now)
    winner = select_primary_link([older, newer])
    assert winner.gateway_id == "gw-new"


def test_select_primary_link_missing_signal_data_never_beats_present_data():
    # Un candidato sin snr/rssi/hops (None) no debe ganarle a otro con datos,
    # aunque sea más reciente.
    now = datetime.now(timezone.utc)
    unknown = _candidate("gw-unknown", last_heard_at=now)
    known = _candidate("gw-known", hops_away=4, snr=-9.0, rssi=-115, last_heard_at=now - timedelta(minutes=10))
    winner = select_primary_link([unknown, known])
    assert winner.gateway_id == "gw-known"


# ── Creación y actualización de enlaces desde node.seen ─────────────────────


async def test_node_seen_creates_link(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "short_name": "AAA", "rssi": -80, "snr": 4.5, "hops_away": 2},
            gateway_id="gw-01",
        )
    )
    async with session_factory() as session:
        links = await SqlNodeGatewayLinkRepository(session).list_for_node(NODE_A)
    assert len(links) == 1
    assert links[0].gateway_id == "gw-01"
    assert links[0].rssi == -80
    assert links[0].snr == 4.5
    assert links[0].hops_away == 2
    assert links[0].first_heard_at is not None
    assert links[0].last_heard_at is not None


async def test_node_seen_updates_existing_link_without_losing_data_on_partial_sighting(session_factory):
    ingest = IngestService(session_factory)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=1)
    t1 = datetime.now(timezone.utc)

    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODE_A, "rssi": -80, "snr": 4.5, "hops_away": 2}, gateway_id="gw-01", ts=t0)
    )
    # Segundo avistamiento parcial (sin snr/hops_away en el payload): no debe
    # borrar lo que ya sabíamos de esa pasarela, mismo criterio que
    # upsert_from_sighting para los campos de identidad.
    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODE_A, "rssi": -70}, gateway_id="gw-01", ts=t1)
    )

    async with session_factory() as session:
        links = await SqlNodeGatewayLinkRepository(session).list_for_node(NODE_A)
    assert len(links) == 1
    link = links[0]
    assert link.rssi == -70  # sí se actualiza, venía en el payload
    assert link.snr == 4.5  # se conserva, no vino en el segundo payload
    assert link.hops_away == 2  # ídem


async def test_node_seen_without_gateway_id_does_not_create_link(session_factory):
    ingest = IngestService(session_factory)
    event = make_event("node.seen", {"node_id": NODE_A, "short_name": "AAA"})
    event["gateway_id"] = None
    await ingest.handle_event(event)

    async with session_factory() as session:
        links = await SqlNodeGatewayLinkRepository(session).list_for_node(NODE_A)
        node = await SqlNodeRepository(session).get(NODE_A)
    assert links == []
    assert node is not None
    assert node.short_name == "AAA"  # la identidad sí se actualiza


# ── Backfill de la caché en `nodes` desde el enlace ganador ─────────────────


async def test_single_gateway_cache_matches_previous_behavior(session_factory):
    """Criterio de aceptación explícito: con una sola pasarela, la caché de
    `nodes` (gateway_id/rssi/snr/hops_away) debe quedar exactamente igual
    que si M6.1 no existiera."""
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "short_name": "AAA", "rssi": -80, "snr": 4.5, "hops_away": 2, "via_mqtt": False},
            gateway_id="gw-01",
        )
    )
    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
    assert node.gateway_id == "gw-01"
    assert node.rssi == -80
    assert node.snr == 4.5
    assert node.hops_away == 2
    assert node.via_mqtt is False


async def test_two_gateways_hear_same_node_cache_picks_best_by_ranking(session_factory):
    """Simula dos pasarelas oyendo al mismo nodo (aunque en producción, en
    M6.1, esto solo ocurriría con Multi-Gateway real desplegado): la caché
    de `nodes` debe reflejar la que gane el ranking del §6, no la última
    en escribir."""
    ingest = IngestService(session_factory)
    t0 = datetime.now(timezone.utc) - timedelta(seconds=30)
    t1 = datetime.now(timezone.utc)

    # gw-far: la oye con más saltos y peor señal, pero es la MÁS RECIENTE.
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "rssi": -115, "snr": -9.0, "hops_away": 4},
            gateway_id="gw-far",
            ts=t1,
        )
    )
    # gw-near: menos saltos y mejor señal, pero más antigua.
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "rssi": -40, "snr": 6.0, "hops_away": 1},
            gateway_id="gw-near",
            ts=t0,
        )
    )

    async with session_factory() as session:
        links = await SqlNodeGatewayLinkRepository(session).list_for_node(NODE_A)
        node = await SqlNodeRepository(session).get(NODE_A)

    assert {link.gateway_id for link in links} == {"gw-far", "gw-near"}
    # Gana gw-near: menos saltos pesa más que la recencia.
    assert node.gateway_id == "gw-near"
    assert node.rssi == -40
    assert node.snr == 6.0
    assert node.hops_away == 1


async def test_manual_priority_overrides_signal_quality_in_cache(session_factory):
    ingest = IngestService(session_factory)
    async with session_factory() as session, session.begin():
        # priority es configuración gestionada (M5): se fija con configure(),
        # nunca con upsert() (eso es solo heartbeat, ADR 0021).
        await SqlGatewayRepository(session).configure(
            "gw-priority",
            name="Prioritaria",
            transport_type="usb",
            connection_params={},
            enabled=True,
            priority=10,
            desired_status="connected",
        )
        await SqlGatewayRepository(session).configure(
            "gw-default",
            name="Normal",
            transport_type="usb",
            connection_params={},
            enabled=True,
            priority=0,
            desired_status="connected",
        )

    now = datetime.now(timezone.utc)
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "rssi": -110, "snr": -8.0, "hops_away": 5},
            gateway_id="gw-priority",
            ts=now,
        )
    )
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "rssi": -30, "snr": 8.0, "hops_away": 0},
            gateway_id="gw-default",
            ts=now,
        )
    )

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
    assert node.gateway_id == "gw-priority"


async def test_stale_link_excluded_from_primary_selection(session_factory):
    """Un enlace stale no debe poder convertirse en pasarela primaria aunque
    tenga mejor señal — solo participan los enlaces activos (§1.3)."""
    ingest = IngestService(session_factory, node_offline_after_seconds=60)
    now = datetime.now(timezone.utc)
    stale_ts = now - timedelta(seconds=120)

    # Enlace viejo (stale) con muy buena señal.
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "rssi": -30, "snr": 10.0, "hops_away": 0},
            gateway_id="gw-stale",
            ts=stale_ts,
        )
    )
    # Enlace reciente (activo) con peor señal, pero es el único vigente.
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": NODE_A, "rssi": -110, "snr": -8.0, "hops_away": 5},
            gateway_id="gw-fresh",
            ts=now,
        )
    )

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
    assert node.gateway_id == "gw-fresh"
