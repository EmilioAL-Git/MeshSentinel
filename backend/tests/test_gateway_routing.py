"""M6.2: selección de pasarela al encolar operaciones remotas y reparto de lotes.

La pasarela se fija cuando la operación entra en cola (sin failover durante su
vida, ADR 0013). Con una sola pasarela el resultado debe ser idéntico al
comportamiento anterior a M6.2 (fallback a `nodes.gateway_id`).
"""

import uuid
from datetime import datetime, timedelta, timezone

from noc.adapters.persistence.organization_repositories import SqlGroupRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository, SqlNodeRepository
from noc.application.admin.batches import BatchService
from noc.application.admin.gateway_routing import (
    resolve_gateway,
    resolve_gateways_for_nodes,
    select_gateway_for_node,
    select_gateways_for_nodes,
)
from noc.application.gateway_stats import compute_multi_gateway_stats, scope_to_members
from noc.application.ingest import IngestService
from noc.config import Settings
from noc.domain.nodes.entities import GatewayInfo, Group, Node, NodeGatewayLink

NODE_A = "!000000a1"
NODE_B = "!000000b2"


def make_settings(**overrides) -> Settings:
    overrides.setdefault("admin_rate_limit_per_minute", 1000)
    return Settings(_env_file=None, **overrides)


def make_event(event_type: str, payload: dict, gateway_id: str, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


async def seen(ingest, node_id: str, gateway_id: str, snr: float, hops: int = 0, ts=None):
    await ingest.handle_event(
        make_event(
            "node.seen",
            {"node_id": node_id, "short_name": node_id[-3:], "snr": snr, "rssi": -80, "hops_away": hops},
            gateway_id,
            ts,
        )
    )


async def heartbeat(session_factory, gateway_id: str, status: str = "connected", **config):
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        repo = SqlGatewayRepository(session)
        await repo.upsert(
            GatewayInfo(gateway_id=gateway_id, status=status, transport="simulated", updated_at=now)
        )
        if config:
            await repo.configure(
                gateway_id,
                name=config.get("name", gateway_id),
                transport_type="simulated",
                connection_params={},
                enabled=config.get("enabled", True),
                priority=config.get("priority", 0),
                desired_status="connected",
            )
        await session.commit()


# ── Selección al encolar ──────────────────────────────────────────────────────


async def test_single_gateway_selection_equals_legacy_behavior(session_factory):
    """Con una pasarela, la selección devuelve exactamente nodes.gateway_id
    incluso sin heartbeat registrado (fallback): cero regresión."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    async with session_factory() as session:
        chosen = await select_gateway_for_node(
            session, NODE_A, make_settings(), fallback_gateway_id="gw-01"
        )
    assert chosen == "gw-01"


async def test_selection_prefers_connected_gateway_with_better_link(session_factory):
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=-9.0, hops=3)
    await seen(ingest, NODE_A, "gw-02", snr=8.0, hops=0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session:
        chosen = await select_gateway_for_node(session, NODE_A, make_settings())
    assert chosen == "gw-02"


async def test_selection_skips_disconnected_gateway(session_factory):
    """La pasarela con mejor señal está caída: gana la conectada."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=-9.0, hops=3)
    await seen(ingest, NODE_A, "gw-02", snr=8.0, hops=0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02", status="disconnected")
    async with session_factory() as session:
        chosen = await select_gateway_for_node(session, NODE_A, make_settings())
    assert chosen == "gw-01"


async def test_selection_skips_stale_link(session_factory):
    """Un enlace viejo (más allá del umbral online/offline) nunca gana aunque
    tenga mejor señal."""
    ingest = IngestService(session_factory)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    await seen(ingest, NODE_A, "gw-02", snr=10.0, hops=0, ts=old)
    await seen(ingest, NODE_A, "gw-01", snr=-9.0, hops=3)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session:
        chosen = await select_gateway_for_node(session, NODE_A, make_settings())
    assert chosen == "gw-01"


async def test_selection_respects_manual_priority(session_factory):
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=-9.0, hops=3)
    await seen(ingest, NODE_A, "gw-02", snr=8.0, hops=0)
    await heartbeat(session_factory, "gw-01", priority=10)
    await heartbeat(session_factory, "gw-02", priority=0)
    async with session_factory() as session:
        chosen = await select_gateway_for_node(session, NODE_A, make_settings())
    assert chosen == "gw-01"


async def test_selection_falls_back_to_cached_gateway_when_no_candidates(session_factory):
    """Sin candidatos válidos (todas caídas), el fallback preserva el
    comportamiento pre-M6.2: la operación se encola por la primaria cacheada."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01", status="error")
    async with session_factory() as session:
        chosen = await select_gateway_for_node(
            session, NODE_A, make_settings(), fallback_gateway_id="gw-01"
        )
    assert chosen == "gw-01"


async def test_fallback_never_returns_soft_deleted_gateway(session_factory):
    """La pasarela cacheada fue eliminada (borrado lógico): el fallback NO la
    resucita — la operación queda no enrutable (None)."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01", name="Vieja")
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        await SqlGatewayRepository(session).soft_delete("gw-01", now)
        await session.commit()
    async with session_factory() as session:
        chosen = await select_gateway_for_node(
            session, NODE_A, make_settings(), fallback_gateway_id="gw-01"
        )
    assert chosen is None


async def test_fallback_never_returns_disabled_gateway(session_factory):
    """Pasarela deshabilitada a propósito por el operador: ni candidata ni
    fallback, aunque su enlace y su heartbeat estén frescos."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01", enabled=False)
    async with session_factory() as session:
        chosen = await select_gateway_for_node(
            session, NODE_A, make_settings(), fallback_gateway_id="gw-01"
        )
    assert chosen is None


async def test_fallback_allowed_for_gateway_without_row(session_factory):
    """Sin fila en gateways (nunca ha enviado heartbeat, arranque en frío):
    el fallback se permite — comportamiento pre-M6.2 intacto."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    async with session_factory() as session:
        chosen = await select_gateway_for_node(
            session, NODE_A, make_settings(), fallback_gateway_id="gw-01"
        )
    assert chosen == "gw-01"


async def test_deleted_gateway_with_active_link_is_not_a_candidate_either(session_factory):
    """Aunque la pasarela eliminada siga emitiendo (proceso vivo), ni el
    filtro de candidatos ni el fallback la eligen: gana la otra."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=10.0, hops=0)  # mejor señal
    await seen(ingest, NODE_A, "gw-02", snr=-9.0, hops=3)
    await heartbeat(session_factory, "gw-01", name="Retirada")
    await heartbeat(session_factory, "gw-02")
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        await SqlGatewayRepository(session).soft_delete("gw-01", now)
        await session.commit()
    # El heartbeat posterior al borrado no lo revierte (upsert nunca toca config)
    await heartbeat(session_factory, "gw-01")
    async with session_factory() as session:
        chosen = await select_gateway_for_node(
            session, NODE_A, make_settings(), fallback_gateway_id="gw-01"
        )
    assert chosen == "gw-02"


async def test_bulk_selection_routes_each_node_by_its_own_gateway(session_factory):
    """Dos mallas independientes: cada nodo sale por SU pasarela."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await seen(ingest, NODE_B, "gw-02", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session:
        selected = await select_gateways_for_nodes(
            session, {NODE_A: None, NODE_B: None}, make_settings()
        )
    assert selected == {NODE_A: "gw-01", NODE_B: "gw-02"}


# ── Selección inteligente de gateway (jerarquía de 4 niveles) ────────────────


async def test_resolve_forced_wins_even_if_gateway_down(session_factory):
    """Nivel 1: forzado siempre gana, sin comprobar disponibilidad."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    async with session_factory() as session:
        resolution = await resolve_gateway(
            session, NODE_A, make_settings(), forced_gateway_id="gw-99-offline"
        )
    assert resolution.gateway_id == "gw-99-offline"
    assert resolution.source == "forced"
    assert resolution.note is None


async def test_resolve_node_preference_used_when_eligible(session_factory):
    """Nivel 2: preferencia del nodo, pasarela operativa -> se usa tal cual."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session, session.begin():
        await SqlNodeRepository(session).set_preferred_gateway(NODE_A, "gw-02")
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings())
    assert resolution.gateway_id == "gw-02"
    assert resolution.source == "node_preferred"
    assert resolution.note is None


async def test_resolve_node_preference_falls_back_with_note_when_unavailable(session_factory):
    """Preferencia blanda: si la pasarela preferida no está operativa, cae al
    automático Y explica por qué — nunca falla mientras haya alternativa."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")  # gw-02 nunca manda heartbeat: no elegible
    async with session_factory() as session, session.begin():
        await SqlNodeRepository(session).set_preferred_gateway(NODE_A, "gw-02")
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings())
    assert resolution.gateway_id == "gw-01"
    assert resolution.source == "auto"
    assert resolution.note is not None
    assert "gw-02" in resolution.note and "gw-01" in resolution.note


async def test_resolve_group_preference_used_when_node_has_none(session_factory):
    """Nivel 3: sin preferencia propia, hereda la del grupo."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session, session.begin():
        groups = SqlGroupRepository(session)
        g = await groups.create(Group(name="Routers"))
        await groups.add_member(g.id, NODE_A)
        await groups.set_preferred_gateway(g.id, "gw-02")
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings())
    assert resolution.gateway_id == "gw-02"
    assert resolution.source == "group_preferred"


async def test_resolve_node_preference_beats_group_preference(session_factory):
    """Nivel 2 > Nivel 3: la preferencia propia del nodo manda sobre la del grupo."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session, session.begin():
        groups = SqlGroupRepository(session)
        g = await groups.create(Group(name="Routers"))
        await groups.add_member(g.id, NODE_A)
        await groups.set_preferred_gateway(g.id, "gw-02")
        await SqlNodeRepository(session).set_preferred_gateway(NODE_A, "gw-01")
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings())
    assert resolution.gateway_id == "gw-01"
    assert resolution.source == "node_preferred"


async def test_resolve_no_preference_falls_through_to_automatic(session_factory):
    """Nivel 4: sin ninguna preferencia, comportamiento automático de siempre."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings())
    assert resolution.gateway_id == "gw-01"
    assert resolution.source == "auto"
    assert resolution.note is None


async def test_resolve_use_preference_false_skips_preference_chain(session_factory):
    """Selector de operación en modo "Automático": ignora deliberadamente
    node/group preferido, va directo al Nivel 4."""
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session, session.begin():
        await SqlNodeRepository(session).set_preferred_gateway(NODE_A, "gw-02")
    async with session_factory() as session:
        resolution = await resolve_gateway(session, NODE_A, make_settings(), use_preference=False)
    assert resolution.gateway_id == "gw-01"
    assert resolution.source == "auto"


async def test_resolve_gateways_for_nodes_bulk_mixes_sources_in_one_call(session_factory):
    """La versión en bloque resuelve nodos con distinto origen (forzado no
    aplica aquí — es global a la llamada) en una sola pasada, coste constante."""
    ingest = IngestService(session_factory)
    node_c = "!000000c3"
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await seen(ingest, NODE_B, "gw-01", snr=5.0)
    await seen(ingest, node_c, "gw-01", snr=5.0)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")
    async with session_factory() as session, session.begin():
        await SqlNodeRepository(session).set_preferred_gateway(NODE_A, "gw-02")  # elegible
        # NODE_B y node_c sin preferencia -> automático
    async with session_factory() as session:
        result = await resolve_gateways_for_nodes(
            session, [NODE_A, NODE_B, node_c], make_settings()
        )
    assert result[NODE_A].gateway_id == "gw-02"
    assert result[NODE_A].source == "node_preferred"
    assert result[NODE_B].source == "auto"
    assert result[node_c].source == "auto"


# ── Reparto de lotes ─────────────────────────────────────────────────────────


async def test_batch_create_distributes_operations_across_gateways(session_factory):
    ingest = IngestService(session_factory)
    await seen(ingest, NODE_A, "gw-01", snr=5.0)
    await seen(ingest, NODE_B, "gw-02", snr=5.0)
    # NODE_B también lo oye gw-01, pero mucho peor y con más saltos
    await seen(ingest, NODE_B, "gw-01", snr=-12.0, hops=4)
    await heartbeat(session_factory, "gw-01")
    await heartbeat(session_factory, "gw-02")

    batches = BatchService(session_factory, make_settings())
    batch = await batches.create(
        name="multi",
        operation_type="metadata.get",
        params={},
        node_ids=[NODE_A, NODE_B],
        scope_description=None,
    )
    from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository

    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(None, None, 100)
    by_node = {op.target_node_id: op for op in ops if op.batch_id == batch.id}
    assert by_node[NODE_A].gateway_id == "gw-01"
    assert by_node[NODE_B].gateway_id == "gw-02"


# ── Estadísticas Multi-Gateway (función pura) ────────────────────────────────


def _link(node_id: str, gateway_id: str, minutes_ago: int = 0) -> NodeGatewayLink:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return NodeGatewayLink(node_id=node_id, gateway_id=gateway_id, last_heard_at=ts, first_heard_at=ts)


def _gateway(gateway_id: str, **kwargs) -> GatewayInfo:
    base = dict(status="connected", transport="simulated", updated_at=datetime.now(timezone.utc))
    base.update(kwargs)
    return GatewayInfo(gateway_id=gateway_id, **base)


def test_stats_exclusive_shared_and_redundancy():
    now = datetime.now(timezone.utc)
    links = [
        _link("!00000001", "gw-01"),
        _link("!00000002", "gw-01"),
        _link("!00000002", "gw-02"),  # compartido
        _link("!00000003", "gw-02"),
        _link("!00000004", "gw-01", minutes_ago=120),  # stale: no cuenta
    ]
    nodes = [
        Node(node_id="!00000001", gateway_id="gw-01"),
        Node(node_id="!00000002", gateway_id="gw-02"),
        Node(node_id="!00000003", gateway_id="gw-02"),
        Node(node_id="!00000004", gateway_id="gw-01"),
    ]
    stats = compute_multi_gateway_stats(
        links, [_gateway("gw-01"), _gateway("gw-02")], nodes, 900, now
    )
    assert stats.nodes_observed == 3
    assert stats.nodes_shared == 1
    assert stats.redundancy_percent == 33.3
    gw1 = next(g for g in stats.gateways if g.gateway_id == "gw-01")
    gw2 = next(g for g in stats.gateways if g.gateway_id == "gw-02")
    assert (gw1.nodes_visible, gw1.nodes_exclusive, gw1.nodes_shared) == (2, 1, 1)
    assert (gw2.nodes_visible, gw2.nodes_exclusive, gw2.nodes_shared) == (2, 1, 1)
    assert gw1.primary_for == 2  # !01 y !04 (la primaria cacheada no exige enlace activo)
    assert gw2.primary_for == 2
    # last_heard_at incluye enlaces stale (última actividad histórica)
    assert gw1.last_heard_at is not None


def test_stats_ignore_ignored_nodes_and_deleted_gateways():
    now = datetime.now(timezone.utc)
    links = [_link("!00000001", "gw-01"), _link("!00000002", "gw-01")]
    nodes = [
        Node(node_id="!00000001", gateway_id="gw-01"),
        Node(node_id="!00000002", gateway_id="gw-01", is_ignored=True),
    ]
    gateways = [_gateway("gw-01"), _gateway("gw-99", deleted_at=now)]
    stats = compute_multi_gateway_stats(links, gateways, nodes, 900, now)
    assert stats.nodes_observed == 1
    assert [g.gateway_id for g in stats.gateways] == ["gw-01"]
    assert stats.gateways[0].nodes_visible == 1
    assert stats.gateways[0].primary_for == 1


def test_scope_to_members_filters_stats_to_group():
    """Flota orientada a grupos: /gateways/stats?group_id= reutiliza
    compute_multi_gateway_stats tal cual, solo restringido a los miembros."""
    now = datetime.now(timezone.utc)
    links = [
        _link("!00000001", "gw-01"),
        _link("!00000002", "gw-01"),
        _link("!00000002", "gw-02"),
        _link("!00000003", "gw-02"),
    ]
    nodes = [
        Node(node_id="!00000001", gateway_id="gw-01"),
        Node(node_id="!00000002", gateway_id="gw-02"),
        Node(node_id="!00000003", gateway_id="gw-02"),
    ]
    gateways = [_gateway("gw-01"), _gateway("gw-02")]
    member_ids = {"!00000001", "!00000002"}  # !00000003 fuera del grupo

    scoped_nodes, scoped_links = scope_to_members(nodes, links, member_ids)
    stats = compute_multi_gateway_stats(scoped_links, gateways, scoped_nodes, 900, now)

    assert stats.nodes_observed == 2  # !00000003 excluido
    assert stats.nodes_shared == 1  # !00000002 sigue compartido
    gw2 = next(g for g in stats.gateways if g.gateway_id == "gw-02")
    assert gw2.nodes_visible == 1  # solo !00000002 del grupo, no !00000003
    assert gw2.primary_for == 1  # !00000003 no cuenta pese a tener gw-02 como primaria
