"""JenTastic-Nexus (ADR 0027): interruptor global + detección de nodos JT.

Guard clause en TODO endpoint salvo la propia lectura del interruptor
(`GET /mode`, la necesita el frontend para decidir si carga el módulo): con
el modo OFF, `POST /scan` devuelve 404 — ni siquiera se manda el comando al
gateway. El marcado (`PUT /nodes/{id}/nexus`) vive en `routers/nodes.py`
junto a favorite/ignored (mismo patrón, ADR 0027 lo hereda de M1.2); aquí
solo la sugerencia — activa (`POST /scan`, manda una difusión y espera) o
pasiva (`GET /passive-candidates`, solo observa tráfico ya visto, nunca
envía nada; `POST /passive-candidates/{node_id}/dismiss` la descarta).
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from noc.adapters.api.deps import RequireManagerDep, SessionDep
from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.nexus.builder import NexusCommandError
from noc.application.nexus.catalog import COMMANDS, CommandSpec, describe
from noc.application.nexus.syntax import syntax_for
from noc.application.nexus_gateway import NexusGateway, NexusScanCooldownError, PassiveCandidate
from noc.application.nexus_conversation import NexusConversationService
from noc.application.nexus_operations import NexusOperationService, NexusTargetError
from noc.application.nexus_settings import NexusSettingError, merge_settings, validate_changes
from noc.domain.nexus.entities import NexusOperation, NexusOperationResponse

router = APIRouter(prefix="/nexus", tags=["nexus"])


def _service(request: Request) -> NexusGateway:
    return request.app.state.nexus_gateway


def _operations(request: Request) -> NexusOperationService:
    return request.app.state.nexus_operations


def _conversation(request: Request) -> NexusConversationService:
    return request.app.state.nexus_conversation


class ModeOut(BaseModel):
    enabled: bool


class ModePatchIn(BaseModel):
    enabled: bool


class SyntaxArgOut(BaseModel):
    name: str
    label: str
    kind: str  # syntax.ArgKind
    choices: list[str]
    min: int | None
    max: int | None
    optional: bool
    placeholder: str
    hint: str
    on_value: str
    off_value: str


class SyntaxVariantOut(BaseModel):
    label: str
    tokens: list[str]
    args: list[SyntaxArgOut]
    note: str
    verified: bool


class CatalogEntryOut(BaseModel):
    name: str
    category: str
    aliases: list[str]
    mutation: str  # "never"|"always"|"with_args" (catalog.Mutation)
    destructive: bool
    busy_seconds: float
    broadcast_forbidden: bool
    description: str  # "" si no hay entrada documentada (nunca inventado)
    # Ayuda del asistente; vacío = sin sintaxis modelada → texto libre.
    syntax: list[SyntaxVariantOut]

    @classmethod
    def from_spec(cls, spec: CommandSpec) -> "CatalogEntryOut":
        return cls(
            name=spec.name, category=spec.category.value, aliases=list(spec.aliases),
            mutation=spec.mutation.value, destructive=spec.destructive,
            busy_seconds=spec.busy_seconds, broadcast_forbidden=spec.broadcast_forbidden,
            description=describe(spec.name),
            syntax=[
                SyntaxVariantOut(
                    label=v.label, tokens=list(v.tokens), note=v.note, verified=v.verified,
                    args=[
                        SyntaxArgOut(
                            name=a.name, label=a.label, kind=a.kind.value,
                            choices=list(a.choices), min=a.min, max=a.max,
                            optional=a.optional, placeholder=a.placeholder, hint=a.hint,
                            on_value=a.on_value, off_value=a.off_value,
                        )
                        for a in v.args
                    ],
                )
                for v in syntax_for(spec.name)
            ],
        )


@router.get("/catalog", response_model=list[CatalogEntryOut])
async def get_catalog(request: Request, current_user: RequireManagerDep) -> list[CatalogEntryOut]:
    """Catálogo COMPLETO del módulo (`application/nexus/catalog.py`), para
    que la UI ofrezca un explorador por categorías en vez de un campo de
    texto libre — pedido explícito del usuario. Puro (sin red/BD), pero
    detrás del mismo guard del interruptor global que el resto del módulo,
    por consistencia."""
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    return [CatalogEntryOut.from_spec(spec) for _name, spec in sorted(COMMANDS.items())]


class ScanIn(BaseModel):
    gateway_id: str
    window_seconds: float = 30.0


class CandidateOut(BaseModel):
    node_id: str
    short_name: str | None
    version: str | None
    role: str | None
    marker: str | None
    already_marked: bool


class ScanOut(BaseModel):
    candidates: list[CandidateOut]


@router.get("/mode", response_model=ModeOut)
async def get_mode(request: Request) -> ModeOut:
    return ModeOut(enabled=await _service(request).is_mode_enabled())


@router.put("/mode", response_model=ModeOut)
async def set_mode(body: ModePatchIn, request: Request, current_user: RequireManagerDep) -> ModeOut:
    actor = current_user.username if current_user else None
    await _service(request).set_mode_enabled(body.enabled, actor)
    return ModeOut(enabled=body.enabled)


class SettingsOut(BaseModel):
    addressing_mode: str
    command_prefix: str
    channel_name: str | None
    response_window_seconds: float
    scan_cooldown_seconds: float
    passive_detection_enabled: bool
    default_target_kind: str
    default_gateway_id: str | None
    catalog_collapsed_default: bool
    notify_on_broadcast_complete: bool
    hidden_commands: list[str]
    pinned_nodes: list[dict[str, str]]
    templates: list[dict[str, str]]


@router.get("/settings", response_model=SettingsOut)
async def get_nexus_settings(request: Request, session: SessionDep, current_user: RequireManagerDep) -> SettingsOut:
    """Ajustes del módulo (ADR 0027 §13) — bajo la pestaña JenTastic-Nexus
    de Ajustes. Solo lectura para cualquier autenticado; PATCH admin-only,
    mismo criterio que /mode."""
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    overrides = await SqlSystemSettingsRepository(session).list_all()
    return SettingsOut(**merge_settings(overrides))


@router.patch("/settings", response_model=SettingsOut)
async def patch_nexus_settings(
    changes: dict[str, Any], request: Request, session: SessionDep, admin: RequireManagerDep
) -> SettingsOut:
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    actor = admin.username if admin else None
    try:
        validated = validate_changes(changes)
    except NexusSettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo = SqlSystemSettingsRepository(session)
    for full_key, value in validated.items():
        await repo.upsert(full_key, value, actor)
    await session.commit()
    overrides = await repo.list_all()
    return SettingsOut(**merge_settings(overrides))


async def _require_can_transmit(session: SessionDep, gateway_id: str) -> None:
    """ADR 0032: una pasarela de solo recepción no puede emitir comandos Nexus
    (todos viajan como texto a la malla)."""
    gateway = await SqlGatewayRepository(session).get(gateway_id)
    if gateway is not None and not gateway.can_transmit:
        raise HTTPException(
            status_code=409,
            detail=f"La pasarela {gateway_id} es de solo recepción: no puede transmitir a la malla.",
        )


@router.post("/scan", response_model=ScanOut)
async def scan(
    body: ScanIn, request: Request, current_user: RequireManagerDep, session: SessionDep
) -> ScanOut:
    service = _service(request)
    if not await service.is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    await _require_can_transmit(session, body.gateway_id)
    issued_by = current_user.username if current_user else "system"
    try:
        candidates = await service.scan(body.gateway_id, issued_by, body.window_seconds)
    except NexusScanCooldownError as exc:
        raise HTTPException(
            status_code=429,
            detail=f"Escaneo reciente en esta pasarela, reintenta en {exc.retry_after_seconds:.0f}s",
        ) from exc
    # NexusCandidate es slots=True: nunca c.__dict__ (no existe) — getattr
    # explícito, mismo patrón que NodeOut.from_entity (schemas.py).
    return ScanOut(
        candidates=[
            CandidateOut(**{f: getattr(c, f) for f in CandidateOut.model_fields})
            for c in candidates
        ]
    )


class PassiveCandidateOut(BaseModel):
    node_id: str
    short_name: str | None
    gateway_id: str
    sample_text: str
    command: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    match_count: int
    already_marked: bool

    @classmethod
    def from_entity(cls, c: PassiveCandidate) -> "PassiveCandidateOut":
        return cls(**{f: getattr(c, f) for f in cls.model_fields})


@router.get("/passive-candidates", response_model=list[PassiveCandidateOut])
async def list_passive_candidates(request: Request, current_user: RequireManagerDep) -> list[PassiveCandidateOut]:
    """Sugerencias de la detección PASIVA (sin enviar nada): nodos cuyo
    tráfico ya observado tiene forma de respuesta Nexus. Complementa a
    `POST /scan` (activo) — ambas vías comparten el mismo destino final:
    confirmación explícita por `PUT /nodes/{id}/nexus`."""
    service = _service(request)
    if not await service.is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    return [PassiveCandidateOut.from_entity(c) for c in await service.list_passive_candidates()]


@router.post("/passive-candidates/{node_id}/dismiss", status_code=204)
async def dismiss_passive_candidate(node_id: str, request: Request, current_user: RequireManagerDep) -> None:
    service = _service(request)
    if not await service.is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    service.dismiss_passive_candidate(node_id)


# ── Cola de operaciones (ADR 0027 §4) ───────────────────────────────────────
# Vocabulario de operador (M4.1): Pendiente/Enviado/Confirmado/Sin respuesta
# — nunca vocabulario del pipeline de administración (modelo distinto, el
# gateway nunca reporta resultado; ver application/nexus_operations.py).


class OperationIn(BaseModel):
    gateway_id: str
    command: str
    args: list[str] = []
    # broadcast|local|node|mac|group — "device" deliberadamente ausente.
    target_kind: str = "broadcast"
    target_value: str | None = None


class OperationOut(BaseModel):
    id: int
    gateway_id: str
    target_kind: str
    target_value: str | None
    command_name: str
    args: list[str]
    text: str
    destructive: bool
    requires_save: bool
    busy_seconds: float
    status: str
    created_by: str | None
    created_at: datetime | None
    sent_at: datetime | None
    response_at: datetime | None
    response_text: str | None
    response_kind: str | None
    response_data: dict[str, Any] | None

    @classmethod
    def from_entity(cls, op: NexusOperation) -> "OperationOut":
        return cls(**{f: getattr(op, f) for f in cls.model_fields})


class PreviewOut(BaseModel):
    text: str
    destructive: bool
    requires_save: bool
    busy_seconds: float


@router.post("/operations/preview", response_model=PreviewOut)
async def preview_operation(body: OperationIn, request: Request, current_user: RequireManagerDep) -> PreviewOut:
    """Construye con el núcleo puro SIN persistir (dry-run, mismo patrón que
    M2 "simular→CONFIRMAR") — para avisar de comandos destructivos antes de
    encolar de verdad."""
    service = _service(request)
    if not await service.is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    try:
        cmd = await _operations(request).build(body.command, body.args, body.target_kind, body.target_value)
    except (NexusCommandError, NexusTargetError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PreviewOut(
        text=cmd.text, destructive=cmd.destructive, requires_save=cmd.requires_save,
        busy_seconds=cmd.busy_seconds,
    )


@router.post("/operations", response_model=OperationOut)
async def create_operation(
    body: OperationIn, request: Request, current_user: RequireManagerDep, session: SessionDep
) -> OperationOut:
    service = _service(request)
    if not await service.is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    await _require_can_transmit(session, body.gateway_id)
    issued_by = current_user.username if current_user else "system"
    try:
        op = await _operations(request).create(
            body.gateway_id, body.command, body.args, body.target_kind, body.target_value, issued_by
        )
    except (NexusCommandError, NexusTargetError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OperationOut.from_entity(op)


class BatchOperationIn(BaseModel):
    gateway_id: str
    command: str
    args: list[str] = []
    # Nombres cortos (-node), uno por nodo seleccionado en Flota — ADR 0027 §14.
    target_values: list[str]
    interval_seconds: float = 5.0


@router.post("/operations/batch", response_model=list[OperationOut])
async def create_operation_batch(
    body: BatchOperationIn, request: Request, current_user: RequireManagerDep, session: SessionDep
) -> list[OperationOut]:
    """Lote: una operación `-node <shortname>` por cada nodo seleccionado en
    Flota, espaciadas entre sí por `interval_seconds` (ADR 0027 §14) — para
    "toda la flota" se usa `POST /operations` con `target_kind=broadcast`
    (ya llega a todos de una), este endpoint es solo para SUBCONJUNTOS."""
    service = _service(request)
    if not await service.is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    await _require_can_transmit(session, body.gateway_id)
    issued_by = current_user.username if current_user else "system"
    try:
        ops = await _operations(request).create_batch(
            body.gateway_id, body.command, body.args, body.target_values, body.interval_seconds, issued_by
        )
    except (NexusCommandError, NexusTargetError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [OperationOut.from_entity(op) for op in ops]


@router.get("/operations", response_model=list[OperationOut])
async def list_operations(
    request: Request,
    current_user: RequireManagerDep,
    gateway_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[OperationOut]:
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    ops = await _operations(request).list_operations(gateway_id, status, limit)
    return [OperationOut.from_entity(op) for op in ops]


@router.get("/operations/{op_id}", response_model=OperationOut)
async def get_operation(op_id: int, request: Request, current_user: RequireManagerDep) -> OperationOut:
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    op = await _operations(request).get(op_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    return OperationOut.from_entity(op)


class OperationResponseOut(BaseModel):
    id: int
    from_node_id: str
    received_at: datetime | None
    response_text: str
    response_kind: str
    response_data: dict[str, Any] | None

    @classmethod
    def from_entity(cls, r: NexusOperationResponse) -> "OperationResponseOut":
        return cls(**{f: getattr(r, f) for f in cls.model_fields})


@router.get("/operations/{op_id}/responses", response_model=list[OperationResponseOut])
async def list_operation_responses(
    op_id: int, request: Request, current_user: RequireManagerDep
) -> list[OperationResponseOut]:
    """Respuestas individuales de una operación de destino múltiple
    (broadcast/group, ADR 0027 §11) — lista vacía para destinos dirigidos
    (local/node/mac), que nunca escriben aquí."""
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    responses = await _operations(request).list_responses(op_id)
    return [OperationResponseOut.from_entity(r) for r in responses]


class InterpretationOut(BaseModel):
    outcome: str  # ok | error | info
    summary: str
    flag_type: str | None
    flag_present: bool | None
    subject_node_id: str | None
    data: dict[str, Any] | None


class ConversationMessageOut(BaseModel):
    id: int
    from_node_id: str
    sender_label: str
    text: str
    gateway_id: str | None
    channel_index: int
    received_at: datetime | None
    rssi: int | None
    snr: float | None
    hops_away: int | None
    context_op_id: int | None
    interpretation: InterpretationOut | None
    parts: int  # >0: respuesta paginada reensamblada de N mensajes


class ConversationOut(BaseModel):
    messages: list[ConversationMessageOut]
    operations: list[OperationOut]
    channels: list[str]  # "gateway_id#indice" — canales Nexus resueltos por nombre


@router.get("/conversation", response_model=ConversationOut)
async def get_conversation(
    request: Request,
    current_user: RequireManagerDep,
    gateway_id: str | None = None,
    limit: int = Query(default=150, ge=1, le=500),
) -> ConversationOut:
    """Chat del canal Nexus (difusiones persistidas por el monitor de Chat)
    con la cola de operaciones superpuesta y cada respuesta ya interpretada
    ("Nodo X ignorado correctamente")."""
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    conv = await _conversation(request).conversation(gateway_id, limit)
    messages = []
    for cm in conv.messages:
        m, i = cm.message, cm.interpretation
        messages.append(
            ConversationMessageOut(
                id=m.id or 0, from_node_id=m.from_node_id, sender_label=cm.sender_label, text=m.text,
                gateway_id=m.gateway_id, channel_index=m.channel_index, received_at=m.received_at,
                rssi=m.rssi, snr=m.snr, hops_away=m.hops_away, context_op_id=cm.context_op_id,
                parts=cm.parts,
                interpretation=None if i is None else InterpretationOut(
                    outcome=i.outcome, summary=i.summary, flag_type=i.flag_type,
                    flag_present=i.flag_present, subject_node_id=i.subject_node_id, data=i.data,
                ),
            )
        )
    return ConversationOut(
        messages=messages,
        operations=[OperationOut.from_entity(o) for o in conv.operations],
        channels=[f"{gw}#{idx}" for gw, idx in conv.channels],
    )


class KnownFlagOut(BaseModel):
    flag_type: str  # favorite | ignored
    subject_node_id: str
    subject_label: str
    subject_short_name: str | None
    source: str  # confirmation | read
    updated_at: datetime | None


@router.get("/nodes/{node_id}/flags", response_model=list[KnownFlagOut])
async def get_known_flags(node_id: str, request: Request, current_user: RequireManagerDep) -> list[KnownFlagOut]:
    """Favoritos/ignorados CONOCIDOS de un nodo Nexus: lo que sus
    confirmaciones (FAV/UNFAV/IGNORE/UNIGNORE) y lecturas (FAVS/IGNORED)
    han ido acumulando."""
    if not await _service(request).is_mode_enabled():
        raise HTTPException(status_code=404, detail="Modo Nexus/JenTastic desactivado")
    flags = await _conversation(request).known_flags(node_id)
    return [KnownFlagOut(**{f: getattr(k, f) for f in KnownFlagOut.model_fields}) for k in flags]
