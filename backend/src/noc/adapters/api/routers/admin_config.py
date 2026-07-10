"""Editor de configuración del nodo (M1.4).

Endpoints:
- GET  /api/v1/admin/config/schema            — metadatos de todas las secciones
- GET  /api/v1/nodes/{node_id}/config         — valores actuales (últimas GET
                                                  correctas por sección)
- POST /api/v1/nodes/{node_id}/config/refresh — encola GETs para actualizar
- POST /api/v1/nodes/{node_id}/config/apply   — encola SETs para el diff pedido

El editor genera la UI automáticamente a partir del esquema; ni backend ni
frontend contienen lógica por parámetro (M1.4).
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.activity import activity
from noc.application.admin.config_schema import (
    ALL_SECTIONS,
    CONFIG_SECTIONS,
    MODULE_CONFIG_SECTIONS,
    OWNER_SECTION,
    UI_GROUPS,
    apply_order_key,
    to_dict,
    validate_field_value,
)
from noc.application.admin.config_state import load_section_states
from noc.application.admin.gateway_routing import select_gateway_for_node
from noc.application.admin.registry import validate_operation
from noc.config import get_settings
from noc.domain.admin.entities import AdminOperation

router = APIRouter(tags=["admin-config"])


# ── Schemas de I/O ───────────────────────────────────────────────────────────


class ConfigSchemaOut(BaseModel):
    ui_groups: dict[str, list[str]]
    sections: list[dict[str, Any]]


class SectionSnapshotOut(BaseModel):
    section: str
    kind: Literal["config", "module_config", "owner"]
    values: dict[str, Any]
    last_read_at: datetime | None
    last_operation_id: int | None


class ConfigStateOut(BaseModel):
    node_id: str
    sections: list[SectionSnapshotOut]


class RefreshIn(BaseModel):
    sections: list[str] | None = Field(
        default=None, description="Lista de secciones a refrescar (None = todas)"
    )


class ApplyIn(BaseModel):
    sections: dict[str, dict[str, Any]]


class ApplyOut(BaseModel):
    operation_ids: list[int]


# ── /schema (independiente del nodo) ─────────────────────────────────────────


@router.get("/admin/config/schema", response_model=ConfigSchemaOut)
async def config_schema() -> ConfigSchemaOut:
    sections_out = (
        [to_dict(OWNER_SECTION)]
        + [to_dict(s) for s in CONFIG_SECTIONS]
        + [to_dict(s) for s in MODULE_CONFIG_SECTIONS]
    )
    return ConfigSchemaOut(ui_groups=UI_GROUPS, sections=sections_out)


# ── /nodes/{id}/config (valores actuales derivados del historial) ────────────


@router.get("/nodes/{node_id}/config", response_model=ConfigStateOut)
async def get_node_config(node_id: str, session: SessionDep) -> ConfigStateOut:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")

    states = await load_section_states(session, node_id)
    snapshots = [
        SectionSnapshotOut(
            section=s.section,
            kind=s.kind,
            values=s.values,
            last_read_at=s.last_read_at,
            last_operation_id=s.last_operation_id,
        )
        for s in states.values()
    ]
    return ConfigStateOut(node_id=node_id, sections=snapshots)


# ── /nodes/{id}/config/refresh ───────────────────────────────────────────────


async def _emit_created(ops: list[AdminOperation]) -> None:
    for op in ops:
        await activity.operation(op, "created")


async def _create_operation(
    session, node, gateway_id: str, op_type: str, params: dict[str, Any]
) -> AdminOperation:
    """Auxiliar compartido: crea una AdminOperation validada y persistida."""
    settings = get_settings()
    normalized = validate_operation(op_type, params)
    op = await SqlAdminOperationRepository(session).create(
        AdminOperation(
            target_node_id=node.node_id,
            gateway_id=gateway_id,
            operation_type=op_type,
            params=normalized,
            timeout_seconds=settings.admin_default_timeout_seconds,
            max_attempts=settings.admin_max_attempts,
            created_by="admin",
        )
    )
    return op


@router.post("/nodes/{node_id}/config/refresh", response_model=ApplyOut)
async def refresh_node_config(
    node_id: str, body: RefreshIn, session: SessionDep
) -> ApplyOut:
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    gateway_id = await select_gateway_for_node(
        session, node_id, get_settings(), fallback_gateway_id=node.gateway_id
    )
    if not gateway_id:
        raise HTTPException(status_code=409, detail="Node has no known gateway to route through")

    requested = body.sections or list(ALL_SECTIONS.keys())
    ops = []
    for name in requested:
        meta = ALL_SECTIONS.get(name)
        if meta is None:
            raise HTTPException(status_code=422, detail=f"Unknown section: {name}")
        if meta.kind == "owner":
            op_type, params = "nodeinfo.get", {}
        elif meta.kind == "config":
            op_type, params = "config.get", {"section": name}
        else:
            op_type, params = "module_config.get", {"section": name}
        ops.append(await _create_operation(session, node, gateway_id, op_type, params))
    await session.commit()
    await _emit_created(ops)
    return ApplyOut(operation_ids=[op.id or 0 for op in ops])


# ── /nodes/{id}/config/apply ─────────────────────────────────────────────────

# Orden de aplicación (M1.4): definido junto al esquema (apply_order_key);
# también lo usa la sincronización de perfiles (M3).
def _sorted_apply_sections(sections: dict[str, Any]) -> list[str]:
    return sorted(sections.keys(), key=apply_order_key)


@router.post("/nodes/{node_id}/config/apply", response_model=ApplyOut, status_code=201)
async def apply_node_config(
    node_id: str, body: ApplyIn, session: SessionDep
) -> ApplyOut:
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    gateway_id = await select_gateway_for_node(
        session, node_id, get_settings(), fallback_gateway_id=node.gateway_id
    )
    if not gateway_id:
        raise HTTPException(status_code=409, detail="Node has no known gateway to route through")
    if not body.sections:
        raise HTTPException(status_code=422, detail="No sections provided")

    # Validación previa de TODO el payload antes de encolar nada: si un campo
    # es inválido, la aplicación entera se rechaza sin efectos parciales
    resolved: list[tuple[str, str, dict[str, Any]]] = []  # (name, op_type, params)
    for name in _sorted_apply_sections(body.sections):
        meta = ALL_SECTIONS.get(name)
        if meta is None:
            raise HTTPException(status_code=422, detail=f"Unknown section: {name}")
        raw_values = body.sections[name]
        if not isinstance(raw_values, dict) or not raw_values:
            continue  # sección sin cambios
        try:
            if meta.kind == "owner":
                normalized = {}
                for field_name, value in raw_values.items():
                    normalized[field_name] = validate_field_value("owner", field_name, value)
                op_type, params = "owner.set", normalized
            elif meta.kind == "config":
                op_type = "config.set"
                params = {"section": name, "values": raw_values}
            else:
                op_type = "module_config.set"
                params = {"section": name, "values": raw_values}
            # Delega la validación final al registro (respeta cada validator)
            params = validate_operation(op_type, params)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"[{name}] {exc}"
            ) from exc
        resolved.append((name, op_type, params))

    if not resolved:
        raise HTTPException(status_code=422, detail="No changes to apply")

    ops = []
    for _name, op_type, params in resolved:
        ops.append(await _create_operation(session, node, gateway_id, op_type, params))
    await session.commit()
    await _emit_created(ops)
    return ApplyOut(operation_ids=[op.id or 0 for op in ops])
