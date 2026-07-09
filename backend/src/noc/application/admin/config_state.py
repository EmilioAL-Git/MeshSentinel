"""Estado de configuración conocido de un nodo (M1.4/M3).

Deriva los «valores actuales» de cada sección a partir del historial de
operaciones GET correctas (la BD es la única fuente: el NOC nunca sondea la
malla para leer). Compartido por el endpoint /nodes/{id}/config y por la
comparación de perfiles (M3).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import AdminOperationModel
from noc.application.admin.config_schema import ALL_SECTIONS


@dataclass(slots=True)
class SectionState:
    section: str
    kind: str  # "config" | "module_config" | "owner"
    values: dict[str, Any]
    last_read_at: datetime | None
    last_operation_id: int | None

    @property
    def has_snapshot(self) -> bool:
        return self.last_operation_id is not None


def extract_owner_values(result: dict[str, Any]) -> dict[str, Any]:
    # nodeinfo.get devuelve directamente el User (asDict): {shortName, longName, ...}
    out: dict[str, Any] = {}
    if isinstance(result.get("shortName"), str):
        out["short_name"] = result["shortName"]
    if isinstance(result.get("longName"), str):
        out["long_name"] = result["longName"]
    return out


def extract_section_values(result: dict[str, Any], section: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    inner = result.get(section)
    return inner if isinstance(inner, dict) else {}


async def load_section_states(session: AsyncSession, node_id: str) -> dict[str, SectionState]:
    """Última lectura correcta por sección, indexada por nombre de sección.

    Se resuelve en Python sobre un conjunto pequeño: en un nodo administrado
    hay decenas de operaciones a lo sumo por sección.
    """
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

    states: dict[str, SectionState] = {}
    for name, meta in ALL_SECTIONS.items():
        row = latest.get(name)
        if row is None:
            states[name] = SectionState(name, meta.kind, {}, None, None)
            continue
        result = row.result if isinstance(row.result, dict) else {}
        values = (
            extract_owner_values(result)
            if meta.kind == "owner"
            else extract_section_values(result, name)
        )
        states[name] = SectionState(name, meta.kind, values, row.finished_at, row.id)
    return states
