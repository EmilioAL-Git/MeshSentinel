"""Panel "Ajustes": overrides en BD sobre los umbrales operacionales de
Settings, editables sin redeploy. Solo administradores (ADR: mismo criterio
que gestión de usuarios — configuración del sistema, no monitorización)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from noc.adapters.api.deps import RequireAdminDep, SessionDep
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.settings_registry import (
    CATEGORY_LABELS,
    SETTINGS_REGISTRY,
    SettingValidationError,
    apply_overrides,
    coerce_value,
)
from noc.config import get_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingOut(BaseModel):
    key: str
    category: str
    category_label: str
    label: str
    description: str
    value_type: str
    unit: str | None
    min_value: float | None
    default_value: float
    value: float
    overridden: bool


class SettingPatchIn(BaseModel):
    value: float


def _out(spec: Any, default_value: float, value: float, overridden: bool) -> SettingOut:
    return SettingOut(
        key=spec.key,
        category=spec.category,
        category_label=CATEGORY_LABELS[spec.category],
        label=spec.label,
        description=spec.description,
        value_type=spec.value_type,
        unit=spec.unit,
        min_value=spec.min_value,
        default_value=default_value,
        value=value,
        overridden=overridden,
    )


def _spec_or_404(key: str) -> Any:
    spec = next((s for s in SETTINGS_REGISTRY if s.key == key), None)
    if spec is None:
        raise HTTPException(status_code=404, detail="Ajuste desconocido")
    return spec


@router.get("", response_model=list[SettingOut])
async def list_settings(session: SessionDep, _admin: RequireAdminDep) -> list[SettingOut]:
    overrides = await SqlSystemSettingsRepository(session).list_all()
    defaults = get_settings().__class__()  # instancia limpia: solo defaults de env, sin overrides aplicados
    return [
        _out(
            spec,
            getattr(defaults, spec.key),
            overrides.get(spec.key, getattr(defaults, spec.key)),
            spec.key in overrides,
        )
        for spec in SETTINGS_REGISTRY
    ]


@router.patch("/{key}", response_model=SettingOut)
async def patch_setting(key: str, body: SettingPatchIn, session: SessionDep, admin: RequireAdminDep) -> SettingOut:
    spec = _spec_or_404(key)
    try:
        value = coerce_value(spec, body.value)
    except SettingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    actor = admin.username if admin is not None else None
    await SqlSystemSettingsRepository(session).upsert(key, value, actor)
    await session.commit()
    apply_overrides(get_settings(), {key: value})
    defaults = get_settings().__class__()
    return _out(spec, getattr(defaults, spec.key), value, True)


@router.delete("/{key}", response_model=SettingOut)
async def reset_setting(key: str, session: SessionDep, _admin: RequireAdminDep) -> SettingOut:
    spec = _spec_or_404(key)
    await SqlSystemSettingsRepository(session).reset(key)
    await session.commit()
    defaults = get_settings().__class__()
    default_value = getattr(defaults, spec.key)
    apply_overrides(get_settings(), {key: default_value})
    return _out(spec, default_value, default_value, False)
