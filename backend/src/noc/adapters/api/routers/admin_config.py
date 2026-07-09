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
from sqlalchemy import select

from noc.adapters.api.deps import SessionDep
from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.adapters.persistence.models import AdminOperationModel
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.activity import activity
from noc.application.admin.config_schema import (
    ALL_SECTIONS,
    CONFIG_SECTIONS,
    MODULE_CONFIG_SECTIONS,
    OWNER_SECTION,
    UI_GROUPS,
    to_dict,
    validate_field_value,
)
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


def _extract_owner_values(result: dict[str, Any]) -> dict[str, Any]:
    # nodeinfo.get devuelve directamente el User (asDict): {shortName, longName, ...}
    out: dict[str, Any] = {}
    if isinstance(result.get("shortName"), str):
        out["short_name"] = result["shortName"]
    if isinstance(result.get("longName"), str):
        out["long_name"] = result["longName"]
    return out


def _extract_section_values(result: dict[str, Any], section: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    inner = result.get(section)
    return inner if isinstance(inner, dict) else {}


@router.get("/nodes/{node_id}/config", response_model=ConfigStateOut)
async def get_node_config(node_id: str, session: SessionDep) -> ConfigStateOut:
    if await SqlNodeRepository(session).get(node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")

    # Última operación con éxito por tipo+sección. Se resuelve en Python
    # sobre un pequeño conjunto: en un nodo administrado hay decenas de
    # operaciones a lo sumo por sección.
    rows = (
        await session.scalars(
            select(AdminOperationModel)
            .where(
                AdminOperationModel.target_node_id == node_id,
                AdminOperationModel.status.in_(("succeeded", "succeeded_unconfirmed")),
                AdminOperationModel.operation_type.in_(
                    ("nodeinfo.get", "config.get", "module_config.get")
                ),
            )
            .order_by(AdminOperationModel.finished_at.desc())
            .limit(500)
        )
    ).all()

    latest: dict[str, AdminOperationModel] = {}
    for r in rows:
        if r.operation_type == "nodeinfo.get":
            key = "owner"
        else:
            section = (r.params or {}).get("section")
            if not section:
                continue
            key = section
        if key not in latest:
            latest[key] = r

    snapshots: list[SectionSnapshotOut] = []
    for name, meta in ALL_SECTIONS.items():
        row = latest.get(name)
        if row is None:
            snapshots.append(
                SectionSnapshotOut(
                    section=name, kind=meta.kind, values={}, last_read_at=None, last_operation_id=None,
                )
            )
            continue
        result = row.result if isinstance(row.result, dict) else {}
        values = (
            _extract_owner_values(result)
            if meta.kind == "owner"
            else _extract_section_values(result, name)
        )
        snapshots.append(
            SectionSnapshotOut(
                section=name, kind=meta.kind, values=values,
                last_read_at=row.finished_at, last_operation_id=row.id,
            )
        )

    return ConfigStateOut(node_id=node_id, sections=snapshots)


# ── /nodes/{id}/config/refresh ───────────────────────────────────────────────


async def _emit_created(ops: list[AdminOperation]) -> None:
    for op in ops:
        await activity.operation(op, "created")


async def _create_operation(session, node, op_type: str, params: dict[str, Any]) -> AdminOperation:
    """Auxiliar compartido: crea una AdminOperation validada y persistida."""
    settings = get_settings()
    normalized = validate_operation(op_type, params)
    op = await SqlAdminOperationRepository(session).create(
        AdminOperation(
            target_node_id=node.node_id,
            gateway_id=node.gateway_id,
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
    if not node.gateway_id:
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
        ops.append(await _create_operation(session, node, op_type, params))
    await session.commit()
    await _emit_created(ops)
    return ApplyOut(operation_ids=[op.id or 0 for op in ops])


# ── /nodes/{id}/config/apply ─────────────────────────────────────────────────

# Orden de aplicación (M1.4): lo menos disruptivo primero; los cambios que
# pueden reiniciar el nodo (lora, security) al final para no interrumpir el
# resto de operaciones. El scheduler solo pone 1 en vuelo por gateway, así que
# el orden se traduce en el orden de despacho.
_APPLY_ORDER = [
    "owner",
    "display", "device_ui", "position", "bluetooth", "power",
    "network", "device",
    # Módulos (todos SAFE)
    "mqtt", "telemetry", "canned_message", "external_notification", "store_forward",
    "range_test", "serial", "neighbor_info", "ambient_lighting", "detection_sensor",
    "paxcounter", "audio", "remote_hardware", "statusmessage", "traffic_management", "tak",
    # Riesgo mayor al final
    "lora", "security",
]


def _sorted_apply_sections(sections: dict[str, Any]) -> list[str]:
    order = {name: idx for idx, name in enumerate(_APPLY_ORDER)}
    return sorted(sections.keys(), key=lambda n: (order.get(n, 999), n))


@router.post("/nodes/{node_id}/config/apply", response_model=ApplyOut, status_code=201)
async def apply_node_config(
    node_id: str, body: ApplyIn, session: SessionDep
) -> ApplyOut:
    node = await SqlNodeRepository(session).get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.gateway_id:
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
        ops.append(await _create_operation(session, node, op_type, params))
    await session.commit()
    await _emit_created(ops)
    return ApplyOut(operation_ids=[op.id or 0 for op in ops])
