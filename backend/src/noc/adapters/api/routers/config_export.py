"""Exportar/importar la configuración portable a otra instalación (no "todo
el panel" — ver `config_export.py` de persistencia para el alcance exacto)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from noc.adapters.api.deps import RequireAdminDep, SessionDep
from noc.adapters.persistence.config_export import export_config, import_config

router = APIRouter(prefix="/config", tags=["config-export"])


@router.get("/export")
async def export_config_endpoint(session: SessionDep, _admin: RequireAdminDep) -> dict[str, Any]:
    return await export_config(session)


class ImportOut(BaseModel):
    created: dict[str, int]
    skipped_existing: dict[str, int]
    skipped_invalid: list[str]


@router.post("/import", response_model=ImportOut)
async def import_config_endpoint(
    body: dict[str, Any], session: SessionDep, _admin: RequireAdminDep
) -> ImportOut:
    if not isinstance(body, dict) or "schema_version" not in body:
        raise HTTPException(status_code=422, detail="Archivo de configuración no reconocido")
    async with session.begin():
        report = await import_config(session, body)
    return ImportOut(
        created=report.created, skipped_existing=report.skipped_existing, skipped_invalid=report.skipped_invalid
    )
