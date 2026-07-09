"""M3 Configuration Profiles: validación, versionado, diff y sync vía batches.

El diff debe entender la semántica de asDict del firmware: camelCase y
omisión de defaults proto3 (ausencia == default). La sincronización crea un
lote estándar del Batch Engine con SOLO los campos diferentes.
"""

import uuid
from datetime import datetime, timezone

import pytest

from noc.adapters.persistence.admin_repositories import (
    SqlAdminBatchRepository,
    SqlAdminOperationRepository,
)
from noc.adapters.persistence.profile_repositories import SqlConfigProfileRepository
from noc.application.admin.batches import BatchService
from noc.application.admin.profiles import (
    ProfileService,
    diff_sections,
    validate_profile_sections,
)
from noc.application.admin.config_state import SectionState
from noc.application.ingest import IngestService
from noc.config import Settings
from noc.domain.admin.entities import AdminOperation

NODE = "!00000001"
NODE2 = "!00000002"


def make_settings() -> Settings:
    return Settings(_env_file=None, admin_rate_limit_per_minute=1000)


def make_event(event_type: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def seed_nodes(session_factory, node_ids=(NODE,)) -> None:
    ingest = IngestService(session_factory)
    for node_id in node_ids:
        await ingest.handle_event(make_event("node.seen", {"node_id": node_id, "short_name": "N"}))


async def seed_snapshot(session_factory, node_id: str, section: str, values: dict) -> None:
    """Simula una lectura config.get correcta ya cerrada (fuente del snapshot)."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session, session.begin():
        op = await SqlAdminOperationRepository(session).create(
            AdminOperation(
                target_node_id=node_id,
                gateway_id="gw-test",
                operation_type="module_config.get" if section in ("telemetry", "mqtt") else "config.get",
                params={"section": section},
            )
        )
        await SqlAdminOperationRepository(session).update_fields(
            op.id or 0,
            {"status": "succeeded", "result": {section: values}, "finished_at": now},
        )


def make_service(session_factory) -> ProfileService:
    settings = make_settings()
    return ProfileService(session_factory, settings, BatchService(session_factory, settings))


PROFILE_SECTIONS = {
    "telemetry": {"device_update_interval": 900, "environment_measurement_enabled": True},
    "display": {"screen_on_secs": 60},
}


# ── Validación ───────────────────────────────────────────────────────────────


def test_validate_rejects_owner_section():
    with pytest.raises(ValueError, match="owner"):
        validate_profile_sections({"owner": {"short_name": "X"}})


def test_validate_rejects_unknown_section_and_field():
    with pytest.raises(ValueError, match="Sección desconocida"):
        validate_profile_sections({"nope": {"x": 1}})
    with pytest.raises(ValueError, match="Unknown field"):
        validate_profile_sections({"display": {"nope": 1}})


def test_validate_rejects_invalid_enum():
    with pytest.raises(ValueError, match="invalid enum"):
        validate_profile_sections({"display": {"units": "PARSECS"}})


def test_validate_normalizes_types():
    out = validate_profile_sections({"display": {"screen_on_secs": "120", "compass_north_top": "true"}})
    assert out["display"] == {"screen_on_secs": 120, "compass_north_top": True}


# ── Diff (puro) ──────────────────────────────────────────────────────────────


def make_state(section: str, values: dict, has_snapshot: bool = True) -> SectionState:
    now = datetime.now(timezone.utc)
    return SectionState(
        section, "config", values, now if has_snapshot else None, 1 if has_snapshot else None
    )


def test_diff_camelcase_and_proto3_defaults():
    profile = validate_profile_sections(
        {"display": {"screen_on_secs": 60, "compass_north_top": False}}
    )
    # El snapshot viene camelCased y omite compass_north_top (default False)
    states = {"display": make_state("display", {"screenOnSecs": 60})}
    diffs = diff_sections(profile, states)
    by_field = {f.field: f for f in diffs[0].fields}
    assert by_field["screen_on_secs"].status == "equal"
    # ausencia == default → False == False → equal
    assert by_field["compass_north_top"].status == "equal"
    assert by_field["compass_north_top"].node_value is False


def test_diff_detects_differences_and_unknown():
    profile = validate_profile_sections(PROFILE_SECTIONS)
    states = {
        "telemetry": make_state(
            "telemetry", {"deviceUpdateInterval": 300, "environmentMeasurementEnabled": True}
        )
        # display: sin snapshot
    }
    diffs = {d.section: d for d in diff_sections(profile, states)}
    tele = {f.field: f for f in diffs["telemetry"].fields}
    assert tele["device_update_interval"].status == "different"
    assert tele["environment_measurement_enabled"].status == "equal"
    assert diffs["telemetry"].different_values == {"device_update_interval": 900}
    assert diffs["display"].has_snapshot is False
    assert all(f.status == "unknown" for f in diffs["display"].fields)


def test_diff_enum_by_name():
    profile = validate_profile_sections({"lora": {"region": "EU_868"}})
    assert diff_sections(profile, {"lora": make_state("lora", {"region": "EU_868"})})[0].fields[0].status == "equal"
    assert diff_sections(profile, {"lora": make_state("lora", {"region": "US"})})[0].fields[0].status == "different"
    # Snapshot sin region → default UNSET (primer valor del enum) ≠ EU_868
    assert diff_sections(profile, {"lora": make_state("lora", {})})[0].fields[0].status == "different"


# ── CRUD + versiones ─────────────────────────────────────────────────────────


async def test_create_and_version_profile(session_factory):
    service = make_service(session_factory)
    profile, v1 = await service.create("Repetidor", "nodos de cerro", PROFILE_SECTIONS)
    assert profile.latest_version == 1
    assert v1.sections["telemetry"]["device_update_interval"] == 900

    with pytest.raises(ValueError, match="Ya existe"):
        await service.create("Repetidor", None, PROFILE_SECTIONS)

    v2 = await service.add_version(
        profile.id or 0,
        {"telemetry": {"device_update_interval": 600}},
        comment="baja cadencia",
    )
    assert v2.version == 2

    async with session_factory() as session:
        repo = SqlConfigProfileRepository(session)
        assert (await repo.get(profile.id or 0)).latest_version == 2
        versions = await repo.list_versions(profile.id or 0)
        assert [v.version for v in versions] == [2, 1]
        # v1 sigue intacta (inmutable)
        assert (await repo.get_version(profile.id or 0, 1)).sections == v1.sections

        listed = await repo.list_profiles()
        assert [(p.name, p.latest_version) for p in listed] == [("Repetidor", 2)]

        assert await repo.delete(profile.id or 0) is True
        assert await repo.list_profiles() == []
        assert await repo.list_versions(profile.id or 0) == []


# ── Comparación con nodo ─────────────────────────────────────────────────────


async def test_compare_against_node(session_factory):
    await seed_nodes(session_factory)
    await seed_snapshot(session_factory, NODE, "telemetry", {"deviceUpdateInterval": 900})
    service = make_service(session_factory)
    profile, _ = await service.create("P", None, PROFILE_SECTIONS)

    _, diffs = await service.compare(profile.id or 0, NODE)
    by_section = {d.section: d for d in diffs}
    tele = {f.field: f for f in by_section["telemetry"].fields}
    assert tele["device_update_interval"].status == "equal"
    # environment_measurement_enabled: perfil True, snapshot omite (False) → different
    assert tele["environment_measurement_enabled"].status == "different"
    assert by_section["display"].has_snapshot is False


# ── Sincronización vía Batch Engine ──────────────────────────────────────────


async def test_sync_only_sends_differences(session_factory):
    await seed_nodes(session_factory, (NODE, NODE2))
    # NODE: telemetry parcialmente distinta, display conforme
    await seed_snapshot(session_factory, NODE, "telemetry", {"deviceUpdateInterval": 300, "environmentMeasurementEnabled": True})
    await seed_snapshot(session_factory, NODE, "display", {"screenOnSecs": 60})
    # NODE2: totalmente conforme
    await seed_snapshot(session_factory, NODE2, "telemetry", {"deviceUpdateInterval": 900, "environmentMeasurementEnabled": True})
    await seed_snapshot(session_factory, NODE2, "display", {"screenOnSecs": 60})

    service = make_service(session_factory)
    profile, _ = await service.create("P", None, PROFILE_SECTIONS)

    preview = await service.sync_preview(profile.id or 0, [NODE, NODE2])
    assert [p.node_id for p in preview.eligible] == [NODE]
    assert preview.eligible[0].sections_to_apply == {
        "telemetry": {"device_update_interval": 900}
    }
    conforme = next(p for p in preview.excluded if p.node_id == NODE2)
    assert "ya conforme" in conforme.blockers[0]
    assert preview.total_operations == 1

    batch = await service.sync(profile.id or 0, [NODE, NODE2])
    assert batch.operation_type == "profile.sync"
    assert batch.params["profile_id"] == profile.id
    assert batch.node_ids == [NODE]

    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 10, batch_id=batch.id
        )
        assert len(ops) == 1
        assert ops[0].operation_type == "module_config.set"
        assert ops[0].params == {"section": "telemetry", "values": {"device_update_interval": 900}}
        assert ops[0].batch_id == batch.id
        # El lote es 100% estándar: el repo/progreso del Batch Engine lo ve
        assert await SqlAdminBatchRepository(session).status_counts(batch.id or 0) == {"pending": 1}


async def test_sync_unknown_sections_policy(session_factory):
    await seed_nodes(session_factory)
    # Sin ningún snapshot: por defecto no hay nada que aplicar
    service = make_service(session_factory)
    profile, _ = await service.create("P", None, {"display": {"screen_on_secs": 60}})

    preview = await service.sync_preview(profile.id or 0, [NODE])
    assert preview.eligible == []
    assert "ya conforme" in preview.excluded[0].blockers[0]
    assert preview.excluded[0].unknown_sections == ["display"]

    with pytest.raises(ValueError, match="Ningún nodo"):
        await service.sync(profile.id or 0, [NODE])

    # include_unknown=True → escribe el perfil completo en esas secciones
    preview2 = await service.sync_preview(profile.id or 0, [NODE], include_unknown=True)
    assert preview2.eligible[0].sections_to_apply == {"display": {"screen_on_secs": 60}}
    batch = await service.sync(profile.id or 0, [NODE], include_unknown=True)
    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 10, batch_id=batch.id
        )
        assert ops[0].operation_type == "config.set"


async def test_sync_orders_sections_by_risk(session_factory):
    await seed_nodes(session_factory)
    await seed_snapshot(session_factory, NODE, "lora", {"hopLimit": 3})
    await seed_snapshot(session_factory, NODE, "display", {"screenOnSecs": 30})
    service = make_service(session_factory)
    profile, _ = await service.create(
        "P", None, {"lora": {"hop_limit": 5}, "display": {"screen_on_secs": 60}}
    )
    batch = await service.sync(profile.id or 0, [NODE])
    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(
            None, None, 10, batch_id=batch.id
        )
    # list_operations ordena por created_at desc → invertimos
    sections = [op.params["section"] for op in reversed(ops)]
    assert sections == ["display", "lora"]  # lora (WARNING) al final
