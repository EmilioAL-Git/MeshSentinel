import uuid
from datetime import datetime, timedelta, timezone

from noc.adapters.persistence.organization_repositories import SqlGroupRepository, SqlTagRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.ingest import IngestService
from noc.application.node_filters import NodeFilters, apply_filters
from noc.domain.nodes.entities import Group, Tag

NODES = ["!00000001", "!00000002", "!00000003"]


def make_event(event_type: str, payload: dict, ts: datetime | None = None, gw: str = "gw-a") -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gw,
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


async def seed(session_factory) -> None:
    ingest = IngestService(session_factory)
    now = datetime.now(timezone.utc)
    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODES[0], "short_name": "ALFA", "long_name": "Nodo Alfa", "hw_model": "TBEAM"})
    )
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": NODES[0], "kind": "device", "battery_level": 15})
    )
    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODES[1], "short_name": "BETA", "hw_model": "RAK4631"}, gw="gw-b")
    )
    # Nodo offline (2h sin actividad)
    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODES[2], "short_name": "MUDO", "hw_model": "TBEAM"}, now - timedelta(hours=2))
    )


async def summaries(session_factory):
    async with session_factory() as session:
        return await SqlNodeRepository(session).list_summaries()


# ── Flags: favoritos e ignorados ─────────────────────────────────────────────


async def test_favorite_and_ignored_flags(session_factory):
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        repo = SqlNodeRepository(session)
        assert (await repo.set_flag(NODES[0], "is_favorite", True)).is_favorite
        assert (await repo.set_flag(NODES[1], "is_ignored", True)).is_ignored
        assert await repo.set_flag("!ffffffff", "is_favorite", True) is None

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODES[0])
    assert node.is_favorite and not node.is_ignored


async def test_node_type_override(session_factory):
    """Clasificación manual (Inspector, Organización): null = 'Automático'."""
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        repo = SqlNodeRepository(session)
        node = await repo.set_node_type_override(NODES[0], "fixed")
        assert node.node_type_override == "fixed"
        assert await repo.set_node_type_override("!ffffffff", "fixed") is None

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODES[0])
    assert node.node_type_override == "fixed"

    async with session_factory() as session, session.begin():
        node = await SqlNodeRepository(session).set_node_type_override(NODES[0], None)
        assert node.node_type_override is None


async def test_node_type_override_bulk(session_factory):
    """Igual que test_node_type_override pero para la selección múltiple de Flota."""
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        repo = SqlNodeRepository(session)
        updated = await repo.set_node_type_override_bulk([NODES[0], NODES[1]], "infra")
        assert updated == 2
        assert await repo.set_node_type_override_bulk([], "infra") == 0

    async with session_factory() as session:
        repo = SqlNodeRepository(session)
        assert (await repo.get(NODES[0])).node_type_override == "infra"
        assert (await repo.get(NODES[1])).node_type_override == "infra"
        assert (await repo.get(NODES[2])).node_type_override is None


async def test_sighting_upsert_preserves_noc_metadata(session_factory):
    """Crítico: un node.seen posterior no debe pisar favoritos/ignorados."""
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        await SqlNodeRepository(session).set_flag(NODES[0], "is_favorite", True)

    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": NODES[0], "snr": 3.5}))

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODES[0])
    assert node.is_favorite is True
    assert node.snr == 3.5


# ── Etiquetas y grupos ───────────────────────────────────────────────────────


async def test_tags_crud_and_assignment(session_factory):
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        tags = SqlTagRepository(session)
        solar = await tags.create(Tag(name="solar", color="#ffcc00"))
        cumbre = await tags.create(Tag(name="cumbre"))
        await tags.set_node_tags(NODES[0], [solar.id, cumbre.id])
        await tags.set_node_tags(NODES[0], [solar.id])  # reemplazo idempotente

    result = await summaries(session_factory)
    by_id = {s.node.node_id: s for s in result}
    assert [t.name for t in by_id[NODES[0]].tags] == ["solar"]
    assert by_id[NODES[1]].tags == []

    # Borrar la etiqueta la desasigna sin romper el nodo
    async with session_factory() as session, session.begin():
        assert await SqlTagRepository(session).delete(solar.id)
    result = await summaries(session_factory)
    assert {s.node.node_id: s.tags for s in result}[NODES[0]] == []


async def test_groups_membership_and_counts(session_factory):
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        groups = SqlGroupRepository(session)
        g = await groups.create(Group(name="Repetidores sierra"))
        await groups.add_member(g.id, NODES[0])
        await groups.add_member(g.id, NODES[1])
        await groups.add_member(g.id, NODES[1])  # idempotente

    async with session_factory() as session:
        groups = SqlGroupRepository(session)
        listed = await groups.list_with_counts()
        assert listed[0].member_count == 2
        assert set(await groups.members(listed[0].id)) == {NODES[0], NODES[1]}

    async with session_factory() as session, session.begin():
        assert await SqlGroupRepository(session).remove_member(listed[0].id, NODES[0])
    result = await summaries(session_factory)
    by_id = {s.node.node_id: s for s in result}
    assert by_id[NODES[1]].group_ids == [listed[0].id]
    assert by_id[NODES[0]].group_ids == []


async def test_groups_bulk_membership(session_factory):
    """Gestión masiva desde Flota: añadir/quitar cientos de nodos de una vez,
    idempotente, sin errores por miembros repetidos o inexistentes."""
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        groups = SqlGroupRepository(session)
        g = await groups.create(Group(name="Routers"))
        await groups.add_member(g.id, NODES[0])  # ya miembro antes del bulk

        added, already = await groups.add_members_bulk(g.id, [NODES[0], NODES[1], NODES[2], NODES[1]])
        assert (added, already) == (2, 1)  # duplicados en la petición se deduplican antes de contar

    async with session_factory() as session:
        assert set(await SqlGroupRepository(session).members(g.id)) == set(NODES)

    async with session_factory() as session, session.begin():
        removed, not_member = await SqlGroupRepository(session).remove_members_bulk(
            g.id, [NODES[0], NODES[1], "!ffffffff"]
        )
        assert (removed, not_member) == (2, 1)

    async with session_factory() as session:
        assert await SqlGroupRepository(session).members(g.id) == [NODES[2]]


# ── Búsqueda avanzada (función pura reutilizable) ────────────────────────────


async def test_apply_filters(session_factory):
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        repo = SqlNodeRepository(session)
        await repo.set_flag(NODES[0], "is_favorite", True)
        await repo.set_flag(NODES[2], "is_ignored", True)
        tags = SqlTagRepository(session)
        solar = await tags.create(Tag(name="solar"))
        await tags.set_node_tags(NODES[0], [solar.id])
        groups = SqlGroupRepository(session)
        g = await groups.create(Group(name="g1"))
        await groups.add_member(g.id, NODES[1])

    all_summaries = await summaries(session_factory)
    t = 900

    def ids(filters: NodeFilters) -> set[str]:
        return {s.node.node_id for s in apply_filters(all_summaries, filters, t)}

    # Ignorados fuera por defecto; visibles con include_ignored; solo ignorados
    assert ids(NodeFilters()) == {NODES[0], NODES[1]}
    assert ids(NodeFilters(include_ignored=True)) == set(NODES)
    assert ids(NodeFilters(only_ignored=True)) == {NODES[2]}
    # Texto sobre nombre, long_name e id
    assert ids(NodeFilters(q="alfa")) == {NODES[0]}
    assert ids(NodeFilters(q="!00000002")) == {NODES[1]}
    # Hardware, etiqueta, grupo, favorito, gateway
    assert ids(NodeFilters(hw_model="RAK4631")) == {NODES[1]}
    assert ids(NodeFilters(tag="solar")) == {NODES[0]}
    assert ids(NodeFilters(group_id=g.id)) == {NODES[1]}
    assert ids(NodeFilters(favorite=True)) == {NODES[0]}
    assert ids(NodeFilters(gateway_id="gw-b")) == {NODES[1]}
    # Online/offline y batería
    assert ids(NodeFilters(online=True)) == {NODES[0], NODES[1]}
    assert ids(NodeFilters(include_ignored=True, online=False)) == {NODES[2]}
    assert ids(NodeFilters(battery_below=20)) == {NODES[0]}
    # Combinación
    assert ids(NodeFilters(hw_model="TBEAM", favorite=True, battery_below=20)) == {NODES[0]}
