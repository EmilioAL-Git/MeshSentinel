"""Perfiles de configuración (M3).

Un perfil es un conjunto parcial o completo de secciones de configuración que
describe un «tipo de nodo». Todo se apoya en infraestructura existente:
- el contenido se valida contra el esquema protobuf introspeccionado (M1.4);
- la comparación usa los snapshots derivados del historial de GETs (config_state);
- la sincronización crea un lote estándar (ADR 0016) con operaciones
  `config.set`/`module_config.set` por nodo — el pipeline de ADR 0013 hace el
  resto (cola, rate limit, merge en gateway, verify read-back, reintentos).

La sección `owner` queda fuera de los perfiles: los nombres son identidad de
cada nodo, no configuración de un tipo (y owner.set no admite bulk a propósito).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.profile_repositories import SqlConfigProfileRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.admin.batches import BatchService, PlannedOperation
from noc.application.admin.config_schema import (
    ALL_SECTIONS,
    apply_order_key,
    field_default,
    field_meta,
    read_snapshot_field,
    validate_field_value,
    values_equal,
)
from noc.application.admin.config_state import SectionState, load_section_states
from noc.config import Settings
from noc.domain.admin.entities import ConfigProfile, ConfigProfileVersion

logger = logging.getLogger("noc.admin.profiles")

FieldStatus = str  # "equal" | "different" | "unknown"


# ── Validación del contenido de un perfil ────────────────────────────────────


def validate_profile_sections(sections: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Valida y normaliza `{section: {field: value}}`. Lanza ValueError."""
    if not isinstance(sections, dict) or not sections:
        raise ValueError("El perfil debe contener al menos una sección con campos")
    normalized: dict[str, dict[str, Any]] = {}
    for section, values in sections.items():
        meta = ALL_SECTIONS.get(section)
        if meta is None:
            raise ValueError(f"Sección desconocida: {section}")
        if meta.kind == "owner":
            raise ValueError(
                "La sección 'owner' no se admite en perfiles: los nombres son identidad "
                "de cada nodo, no configuración de un tipo"
            )
        if not isinstance(values, dict) or not values:
            raise ValueError(f"La sección '{section}' no contiene campos")
        out: dict[str, Any] = {}
        for field_name, value in values.items():
            out[field_name] = validate_field_value(section, field_name, value)
        normalized[section] = out
    return normalized


# ── Comparación perfil ↔ nodo ────────────────────────────────────────────────


@dataclass(slots=True)
class FieldDiff:
    field: str
    kind: str
    profile_value: Any
    node_value: Any  # None si la sección no tiene snapshot
    status: FieldStatus


@dataclass(slots=True)
class SectionDiff:
    section: str
    risk: str
    has_snapshot: bool
    last_read_at: datetime | None
    fields: list[FieldDiff] = field(default_factory=list)

    @property
    def different_values(self) -> dict[str, Any]:
        return {f.field: f.profile_value for f in self.fields if f.status == "different"}


def diff_sections(
    profile_sections: dict[str, dict[str, Any]], states: dict[str, SectionState]
) -> list[SectionDiff]:
    """Diff puro entre el contenido de un perfil y los snapshots de un nodo.

    asDict del firmware omite los valores default de proto3 y usa camelCase:
    la ausencia de un campo en un snapshot existente equivale a su default.
    Sin snapshot de la sección, todos sus campos quedan en 'unknown'.
    """
    diffs: list[SectionDiff] = []
    for section, values in profile_sections.items():
        meta = ALL_SECTIONS[section]
        state = states.get(section)
        has_snapshot = state is not None and state.has_snapshot
        diff = SectionDiff(
            section=section,
            risk=meta.risk,
            has_snapshot=has_snapshot,
            last_read_at=state.last_read_at if state else None,
        )
        for field_name, profile_value in values.items():
            fmeta = field_meta(section, field_name)
            if fmeta is None:
                continue  # el firmware/esquema pudo cambiar; el campo ya no existe
            if not has_snapshot:
                diff.fields.append(
                    FieldDiff(field_name, fmeta.kind, profile_value, None, "unknown")
                )
                continue
            node_value = read_snapshot_field(state.values, field_name)
            if node_value is None:
                node_value = field_default(fmeta)
            status = "equal" if values_equal(fmeta, profile_value, node_value) else "different"
            diff.fields.append(FieldDiff(field_name, fmeta.kind, profile_value, node_value, status))
        diffs.append(diff)
    diffs.sort(key=lambda d: apply_order_key(d.section))
    return diffs


# ── Plan de sincronización ───────────────────────────────────────────────────


@dataclass(slots=True)
class NodeSyncPlan:
    node_id: str
    display_name: str
    eligible: bool
    # Secciones a escribir con SOLO los campos diferentes
    sections_to_apply: dict[str, dict[str, Any]] = field(default_factory=dict)
    change_count: int = 0
    equal_count: int = 0
    unknown_sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def operation_count(self) -> int:
        return len(self.sections_to_apply)


@dataclass(slots=True)
class ProfileSyncPreview:
    profile_id: int
    profile_name: str
    version: int
    include_unknown: bool
    eligible: list[NodeSyncPlan]
    excluded: list[NodeSyncPlan]
    total_operations: int
    estimated_seconds: int


class ProfileService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        batch_service: BatchService,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._batches = batch_service

    # ── CRUD + versiones ─────────────────────────────────────────────────────

    async def create(
        self,
        name: str,
        description: str | None,
        sections: dict[str, Any],
        created_by: str = "admin",
    ) -> tuple[ConfigProfile, ConfigProfileVersion]:
        normalized = validate_profile_sections(sections)
        async with self._session_factory() as session, session.begin():
            repo = SqlConfigProfileRepository(session)
            if await repo.get_by_name(name) is not None:
                raise ValueError(f"Ya existe un perfil llamado '{name}'")
            profile = await repo.create(ConfigProfile(name=name, description=description))
            version = await repo.add_version(
                profile.id or 0, normalized, comment="Versión inicial", created_by=created_by
            )
            profile.latest_version = version.version
        logger.info("profile.created id=%s name=%r", profile.id, name)
        return profile, version

    async def add_version(
        self,
        profile_id: int,
        sections: dict[str, Any],
        comment: str | None,
        created_by: str = "admin",
    ) -> ConfigProfileVersion:
        normalized = validate_profile_sections(sections)
        async with self._session_factory() as session, session.begin():
            repo = SqlConfigProfileRepository(session)
            if await repo.get(profile_id) is None:
                raise ValueError("Profile not found")
            version = await repo.add_version(profile_id, normalized, comment, created_by)
        logger.info("profile.version id=%s v=%d", profile_id, version.version)
        return version

    async def _resolve_version(
        self, session: AsyncSession, profile_id: int, version: int | None
    ) -> tuple[ConfigProfile, ConfigProfileVersion]:
        repo = SqlConfigProfileRepository(session)
        profile = await repo.get(profile_id)
        if profile is None:
            raise ValueError("Profile not found")
        number = version or profile.latest_version
        v = await repo.get_version(profile_id, number)
        if v is None:
            raise ValueError(f"Profile version {number} not found")
        return profile, v

    # ── Comparación ──────────────────────────────────────────────────────────

    async def compare(
        self, profile_id: int, node_id: str, version: int | None = None
    ) -> tuple[ConfigProfileVersion, list[SectionDiff]]:
        async with self._session_factory() as session:
            _, v = await self._resolve_version(session, profile_id, version)
            if await SqlNodeRepository(session).get(node_id) is None:
                raise ValueError("Node not found")
            states = await load_section_states(session, node_id)
        return v, diff_sections(v.sections, states)

    # ── Sincronización vía Batch Engine ──────────────────────────────────────

    async def sync_preview(
        self,
        profile_id: int,
        node_ids: list[str],
        version: int | None = None,
        include_unknown: bool = False,
    ) -> ProfileSyncPreview:
        """Simulación sin efectos: qué se escribiría en cada nodo.

        Solo los campos DIFERENTES viajan a la malla. Las secciones sin
        snapshot no se pueden comparar: se omiten con aviso, salvo que
        include_unknown pida escribir el perfil completo en ellas (el gateway
        fusiona sobre la lectura previa, así que sigue siendo seguro).
        """
        if not node_ids:
            raise ValueError("Selecciona al menos un nodo")
        async with self._session_factory() as session:
            profile, v = await self._resolve_version(session, profile_id, version)
            node_repo = SqlNodeRepository(session)
            threshold = self._settings.node_offline_after_seconds

            eligible: list[NodeSyncPlan] = []
            excluded: list[NodeSyncPlan] = []
            for node_id in dict.fromkeys(node_ids):
                node = await node_repo.get(node_id)
                if node is None:
                    excluded.append(
                        NodeSyncPlan(node_id, node_id, False, blockers=["desconocido en el registry"])
                    )
                    continue
                plan = NodeSyncPlan(
                    node_id, node.long_name or node.short_name or node_id, True
                )
                if not node.gateway_id:
                    plan.blockers.append("sin pasarela conocida (no enrutable)")
                if not node.is_online(threshold):
                    plan.warnings.append("sin conexión reciente: probable timeout")

                states = await load_section_states(session, node_id)
                for diff in diff_sections(v.sections, states):
                    if not diff.has_snapshot:
                        plan.unknown_sections.append(diff.section)
                        if include_unknown:
                            plan.sections_to_apply[diff.section] = dict(v.sections[diff.section])
                            plan.change_count += len(v.sections[diff.section])
                        continue
                    plan.equal_count += sum(1 for f in diff.fields if f.status == "equal")
                    changed = diff.different_values
                    if changed:
                        plan.sections_to_apply[diff.section] = changed
                        plan.change_count += len(changed)
                if plan.unknown_sections and not include_unknown:
                    plan.warnings.append(
                        "secciones sin datos (se omiten): " + ", ".join(plan.unknown_sections)
                    )
                if not plan.blockers and not plan.sections_to_apply:
                    plan.blockers.append("ya conforme con el perfil")
                if plan.blockers:
                    plan.eligible = False
                    excluded.append(plan)
                else:
                    eligible.append(plan)

        total_ops = sum(p.operation_count for p in eligible)
        return ProfileSyncPreview(
            profile_id=profile_id,
            profile_name=profile.name,
            version=v.version,
            include_unknown=include_unknown,
            eligible=eligible,
            excluded=excluded,
            total_operations=total_ops,
            estimated_seconds=self._batches.estimate_seconds(total_ops),
        )

    async def sync(
        self,
        profile_id: int,
        node_ids: list[str],
        version: int | None = None,
        include_unknown: bool = False,
        name: str | None = None,
        created_by: str = "admin",
    ) -> Any:
        """Crea el lote de sincronización. El plan se recalcula en el servidor
        (no se confía en el preview del cliente) y solo viajan diferencias."""
        preview = await self.sync_preview(profile_id, node_ids, version, include_unknown)
        if not preview.eligible:
            raise ValueError("Ningún nodo requiere cambios (o ninguno es elegible)")

        async with self._session_factory() as session:
            node_repo = SqlNodeRepository(session)
            gateways = {
                p.node_id: (await node_repo.get(p.node_id)).gateway_id  # type: ignore[union-attr]
                for p in preview.eligible
            }

        planned: list[PlannedOperation] = []
        for plan in preview.eligible:
            for section in sorted(plan.sections_to_apply, key=apply_order_key):
                meta = ALL_SECTIONS[section]
                op_type = "config.set" if meta.kind == "config" else "module_config.set"
                planned.append(
                    PlannedOperation(
                        node_id=plan.node_id,
                        gateway_id=gateways[plan.node_id] or "",
                        operation_type=op_type,
                        params={"section": section, "values": plan.sections_to_apply[section]},
                    )
                )

        batch = await self._batches.create_planned(
            name=name or f"Perfil {preview.profile_name} v{preview.version}",
            operation_type="profile.sync",
            params={
                "profile_id": profile_id,
                "profile_name": preview.profile_name,
                "version": preview.version,
                "include_unknown": include_unknown,
            },
            planned=planned,
            scope_description={
                "profile": preview.profile_name,
                "version": preview.version,
                "explicit_node_ids": len(preview.eligible),
            },
            created_by=created_by,
        )
        logger.info(
            "profile.sync profile=%s v=%d batch=%s ops=%d",
            profile_id, preview.version, batch.id, len(planned),
        )
        return batch
