"""Endpoints del editor de configuración (M1.4)."""

import uuid
from datetime import datetime, timezone

import pytest

from noc.adapters.api.routers.admin_config import (
    ApplyIn,
    RefreshIn,
    apply_node_config,
    config_schema,
    get_node_config,
    refresh_node_config,
)
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.admin.config_schema import (
    ALL_SECTIONS,
    CONFIG_SECTIONS,
    MODULE_CONFIG_SECTIONS,
    UI_GROUPS,
)
from noc.application.ingest import IngestService
from noc.domain.admin.entities import AdminOperation

NODE = "!a1b2c3d4"


def make_event(event_type: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def seed_node(session_factory) -> None:
    await IngestService(session_factory).handle_event(
        make_event("node.seen", {"node_id": NODE, "short_name": "TEST"})
    )


# ── /schema ──────────────────────────────────────────────────────────────────


async def test_config_schema_endpoint_returns_all_sections():
    schema = await config_schema()
    names = {s["name"] for s in schema.sections}
    assert "owner" in names
    assert {s.name for s in CONFIG_SECTIONS} <= names
    assert {s.name for s in MODULE_CONFIG_SECTIONS} <= names
    assert schema.ui_groups == UI_GROUPS
    # Enum: lora.region debe estar como enum con valores
    lora = next(s for s in schema.sections if s["name"] == "lora")
    region = next(f for f in lora["fields"] if f["name"] == "region")
    assert region["kind"] == "enum"
    assert "EU_868" in region["enum_values"]


# ── /nodes/{id}/config ───────────────────────────────────────────────────────


_finished_counter = 0


async def _record_get_op(
    session_factory, op_type: str, params: dict, result: dict, section: str | None = None,
) -> AdminOperation:
    """SqlAdminOperationRepository.create() no persiste finished_at (los GET
    reales lo reciben del scheduler): lo actualizamos con un instante creciente
    para que el orden temporal sea determinista dentro del test."""
    global _finished_counter
    _finished_counter += 1
    finished = datetime.now(timezone.utc).replace(microsecond=_finished_counter)
    async with session_factory() as session, session.begin():
        repo = SqlAdminOperationRepository(session)
        # create() no persiste result/finished_at (los rellena el tracker en
        # producción); los aplicamos con update_fields tras crear
        op = await repo.create(
            AdminOperation(
                target_node_id=NODE,
                gateway_id="gw-test",
                operation_type=op_type,
                params=params,
                status="succeeded",
            )
        )
        await repo.update_fields(op.id, {"result": result, "finished_at": finished})
    _ = section
    return op


async def test_get_node_config_returns_last_snapshot(session_factory):
    await seed_node(session_factory)
    # 1) Un config.get de lora
    await _record_get_op(
        session_factory, "config.get", {"section": "lora"},
        {"lora": {"region": "EU_868", "hopLimit": 3}},
    )
    # 2) Un nodeinfo.get
    await _record_get_op(
        session_factory, "nodeinfo.get", {},
        {"id": NODE, "shortName": "4IEN", "longName": "Nodo Prueba"},
    )
    # 3) Un module_config.get de telemetry (dos veces: el último debe ganar)
    await _record_get_op(
        session_factory, "module_config.get", {"section": "telemetry"},
        {"telemetry": {"deviceUpdateInterval": 300}},
    )
    await _record_get_op(
        session_factory, "module_config.get", {"section": "telemetry"},
        {"telemetry": {"deviceUpdateInterval": 600}},
    )

    async with session_factory() as session:
        state = await get_node_config(NODE, session)

    by_section = {s.section: s for s in state.sections}
    assert by_section["lora"].values == {"region": "EU_868", "hopLimit": 3}
    assert by_section["owner"].values == {"short_name": "4IEN", "long_name": "Nodo Prueba"}
    assert by_section["telemetry"].values == {"deviceUpdateInterval": 600}
    # Secciones sin lecturas devuelven values vacíos
    assert by_section["mqtt"].values == {}
    assert by_section["mqtt"].last_operation_id is None
    # Todas las secciones del schema aparecen
    assert set(by_section) == set(ALL_SECTIONS.keys())


async def test_get_node_config_404(session_factory):
    async with session_factory() as session:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await get_node_config("!ffffffff", session)
    assert exc.value.status_code == 404


# ── /refresh ─────────────────────────────────────────────────────────────────


async def test_refresh_creates_get_operations(session_factory):
    await seed_node(session_factory)
    async with session_factory() as session:
        out = await refresh_node_config(
            NODE, RefreshIn(sections=["lora", "telemetry", "owner"]), session,
        )
    assert len(out.operation_ids) == 3

    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(None, NODE, 10)
    types = sorted((o.operation_type, (o.params or {}).get("section")) for o in ops)
    assert types == [
        ("config.get", "lora"),
        ("module_config.get", "telemetry"),
        ("nodeinfo.get", None),
    ]
    assert all(o.status == "pending" for o in ops)


async def test_refresh_all_sections_when_body_empty(session_factory):
    await seed_node(session_factory)
    async with session_factory() as session:
        out = await refresh_node_config(NODE, RefreshIn(), session)
    assert len(out.operation_ids) == len(ALL_SECTIONS)


async def test_refresh_rejects_unknown_section(session_factory):
    await seed_node(session_factory)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        async with session_factory() as session:
            await refresh_node_config(NODE, RefreshIn(sections=["nope"]), session)
    assert exc.value.status_code == 422


# ── /apply ───────────────────────────────────────────────────────────────────


async def test_apply_creates_typed_operations_in_order(session_factory):
    await seed_node(session_factory)
    body = ApplyIn(
        sections={
            # Orden alfabético a propósito: debe reordenarse por _APPLY_ORDER
            "lora": {"hop_limit": 5},
            "owner": {"short_name": "AB"},
            "telemetry": {"device_update_interval": 900},
            "display": {"screen_on_secs": 30},
        }
    )
    async with session_factory() as session:
        out = await apply_node_config(NODE, body, session)
    assert len(out.operation_ids) == 4

    async with session_factory() as session:
        ops = sorted(
            await SqlAdminOperationRepository(session).list_operations(None, NODE, 10),
            key=lambda o: o.id or 0,
        )
    # El orden es: owner, display, telemetry, lora
    order = [o.operation_type + ":" + (o.params or {}).get("section", "") for o in ops]
    assert order == [
        "owner.set:",
        "config.set:display",
        "module_config.set:telemetry",
        "config.set:lora",
    ]
    # El SET incluye {section, values}
    lora_op = next(o for o in ops if (o.params or {}).get("section") == "lora")
    assert lora_op.params["values"] == {"hop_limit": 5}


async def test_apply_rejects_invalid_value(session_factory):
    await seed_node(session_factory)
    from fastapi import HTTPException

    body = ApplyIn(sections={"lora": {"region": "MARTE"}})
    with pytest.raises(HTTPException) as exc:
        async with session_factory() as session:
            await apply_node_config(NODE, body, session)
    assert exc.value.status_code == 422
    assert "lora" in exc.value.detail
    # Nada se encoló
    async with session_factory() as session:
        ops = await SqlAdminOperationRepository(session).list_operations(None, NODE, 10)
    assert ops == []


async def test_apply_rejects_no_changes(session_factory):
    await seed_node(session_factory)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        async with session_factory() as session:
            await apply_node_config(NODE, ApplyIn(sections={}), session)
    assert exc.value.status_code == 422
    # Y también si los valores están vacíos por sección
    with pytest.raises(HTTPException) as exc:
        async with session_factory() as session:
            await apply_node_config(NODE, ApplyIn(sections={"lora": {}}), session)
    assert exc.value.status_code == 422


async def test_apply_owner_validation():
    """El validador de owner sigue vigente (M1.3): 4 caracteres máx en short."""
    from noc.application.admin.registry import validate_operation

    with pytest.raises(ValueError):
        validate_operation("owner.set", {"short_name": "DEMASIADO"})
