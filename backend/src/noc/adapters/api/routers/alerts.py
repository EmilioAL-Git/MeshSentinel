from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from noc.adapters.api.deps import RequireAuthDep, SessionDep
from noc.application.alerting.evaluators import GROUP_SCOPE_UNSUPPORTED
from noc.adapters.notifications import PROVIDERS, build_provider
from noc.adapters.persistence.alert_repositories import (
    SqlAlertRepository,
    SqlAlertRuleRepository,
    SqlNotificationChannelRepository,
    SqlNotificationProviderRepository,
)
from noc.domain.alerts.entities import Alert, AlertRule, NotificationChannel, NotificationProviderConfig

router = APIRouter(tags=["alerting"])

# ── Schemas ──────────────────────────────────────────────────────────────────


class AlertOut(BaseModel):
    id: int
    rule_id: int
    rule_name: str
    subject_type: str
    subject_id: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    status: Literal["firing", "acknowledged", "resolved"]
    message: str
    correlation_key: str | None
    fired_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None

    @classmethod
    def from_entity(cls, a: Alert) -> "AlertOut":
        return cls(**{f: getattr(a, f) for f in cls.model_fields})


class AckIn(BaseModel):
    acknowledged_by: str = Field(default="api", max_length=64)


class RuleIn(BaseModel):
    name: str = Field(max_length=128)
    rule_type: Literal[
        "low_battery",
        "node_offline",
        "snr_degraded",
        "gateway_disconnected",
        "gateway_no_traffic",
        "low_redundancy",
        "temperature_high",
        "channel_utilization_high",
        "position_lost",
        "neighbor_link_lost",
    ]
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    enabled: bool = True
    threshold: float | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    cooldown_seconds: int = Field(default=0, ge=0)
    params: dict[str, Any] = {}
    channel_ids: list[int] = []
    # Ámbito de la regla (§1.3 opción A, ampliada): None/None = toda la red.
    # group_id = un grupo de nodos; node_id = un único nodo. Mutuamente
    # excluyentes; ninguno de los dos se admite en reglas cuyo sujeto son
    # pasarelas (GROUP_SCOPE_UNSUPPORTED).
    group_id: int | None = None
    node_id: str | None = None

    @model_validator(mode="after")
    def _scope_supported(self) -> "RuleIn":
        if self.group_id is not None and self.node_id is not None:
            raise ValueError("group_id y node_id son mutuamente excluyentes")
        if (self.group_id is not None or self.node_id is not None) and self.rule_type in GROUP_SCOPE_UNSUPPORTED:
            raise ValueError(
                f"rule_type '{self.rule_type}' no admite escopado por grupo o nodo (sujeto: pasarela)"
            )
        return self


class RulePatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    severity: Literal["INFO", "WARNING", "CRITICAL"] | None = None
    enabled: bool | None = None
    threshold: float | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    cooldown_seconds: int | None = Field(default=None, ge=0)
    params: dict[str, Any] | None = None
    channel_ids: list[int] | None = None


class RuleOut(RuleIn):
    id: int
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, r: AlertRule) -> "RuleOut":
        return cls(**{f: getattr(r, f) for f in cls.model_fields})


class ProviderIn(BaseModel):
    name: str = Field(max_length=128)
    provider: str = Field(max_length=32)
    configuration: dict[str, Any]
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    configuration: dict[str, Any] | None = None
    enabled: bool | None = None


class ProviderOut(BaseModel):
    id: int
    name: str
    provider: str
    configuration: dict[str, Any]
    enabled: bool
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, c: NotificationProviderConfig) -> "ProviderOut":
        return cls(**{f: getattr(c, f) for f in cls.model_fields})


class ChannelIn(BaseModel):
    name: str = Field(max_length=128)
    description: str | None = None
    provider_ids: list[int] = []


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    provider_ids: list[int] | None = None


class ChannelOut(BaseModel):
    id: int
    name: str
    description: str | None
    provider_ids: list[int]
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, c: NotificationChannel) -> "ChannelOut":
        return cls(**{f: getattr(c, f) for f in cls.model_fields})


# ── Alertas ──────────────────────────────────────────────────────────────────


class AlertCountsOut(BaseModel):
    """Agregados reales de alertas activas (hardening): la fuente de los
    contadores del HUD/StatusBar/insignias — nunca una lista truncada."""

    active: int
    firing: int
    acknowledged: int
    critical_active: int


@router.get("/alerts/counts", response_model=AlertCountsOut)
async def alert_counts(session: SessionDep, group_id: int | None = None) -> AlertCountsOut:
    counts = await SqlAlertRepository(session).active_counts(group_id)
    return AlertCountsOut(**{f: counts.get(f, 0) for f in AlertCountsOut.model_fields})


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    session: SessionDep,
    status: Literal["firing", "acknowledged", "resolved"] | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AlertOut]:
    alerts = await SqlAlertRepository(session).list_alerts(status, limit)
    return [AlertOut.from_entity(a) for a in alerts]


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
async def acknowledge_alert(alert_id: int, session: SessionDep, body: AckIn | None = None) -> AlertOut:
    async with session.begin():
        alert = await SqlAlertRepository(session).acknowledge(
            alert_id, (body or AckIn()).acknowledged_by
        )
    if alert is None:
        raise HTTPException(status_code=404, detail="Active alert not found")
    return AlertOut.from_entity(alert)


# ── Reglas ───────────────────────────────────────────────────────────────────


@router.get("/alert-rules", response_model=list[RuleOut])
async def list_rules(session: SessionDep) -> list[RuleOut]:
    rules = await SqlAlertRuleRepository(session).list_all()
    return [RuleOut.from_entity(r) for r in rules]


@router.post("/alert-rules", response_model=RuleOut, status_code=201)
async def create_rule(body: RuleIn, session: SessionDep, _user: RequireAuthDep) -> RuleOut:
    async with session.begin():
        rule = await SqlAlertRuleRepository(session).create(AlertRule(**body.model_dump()))
    return RuleOut.from_entity(rule)


@router.patch("/alert-rules/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, body: RulePatch, session: SessionDep, _user: RequireAuthDep) -> RuleOut:
    changes = body.model_dump(exclude_unset=True)
    async with session.begin():
        rule = await SqlAlertRuleRepository(session).update(rule_id, changes)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RuleOut.from_entity(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, session: SessionDep, _user: RequireAuthDep) -> None:
    async with session.begin():
        deleted = await SqlAlertRuleRepository(session).delete(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")


# En modo protegido, crear/editar/borrar reglas, integraciones y canales
# exige sesión (las integraciones además hacen que el backend haga POST a
# URLs/APIs arbitrarias). El ACK de alertas queda abierto a propósito: es
# triaje, no configuración.
# ── Integraciones (instancias de proveedor) ─────────────────────────────────


@router.get("/notification-providers", response_model=list[ProviderOut])
async def list_providers(session: SessionDep) -> list[ProviderOut]:
    providers = await SqlNotificationProviderRepository(session).list_all()
    return [ProviderOut.from_entity(p) for p in providers]


@router.post("/notification-providers", response_model=ProviderOut, status_code=201)
async def create_provider(body: ProviderIn, session: SessionDep, _user: RequireAuthDep) -> ProviderOut:
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {body.provider}")
    errors = build_provider(NotificationProviderConfig(**body.model_dump())).validate()
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    async with session.begin():
        provider = await SqlNotificationProviderRepository(session).create(
            NotificationProviderConfig(**body.model_dump())
        )
    return ProviderOut.from_entity(provider)


@router.patch("/notification-providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int, body: ProviderPatch, session: SessionDep, _user: RequireAuthDep
) -> ProviderOut:
    # El SELECT previo (validar configuration) ya abre la transacción implícita
    # de la sesión, por lo que aquí NO puede usarse session.begin(): se cierra
    # con commit() (mismo patrón que admin_operations.create_operation).
    if body.configuration is not None:
        current = await SqlNotificationProviderRepository(session).get(provider_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        errors = build_provider(
            NotificationProviderConfig(name=current.name, provider=current.provider, configuration=body.configuration)
        ).validate()
        if errors:
            raise HTTPException(status_code=422, detail=errors)
    provider = await SqlNotificationProviderRepository(session).update(
        provider_id, body.model_dump(exclude_unset=True)
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    await session.commit()
    return ProviderOut.from_entity(provider)


@router.delete("/notification-providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: int, session: SessionDep, _user: RequireAuthDep) -> None:
    async with session.begin():
        deleted = await SqlNotificationProviderRepository(session).delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")


@router.post("/notification-providers/{provider_id}/test")
async def test_provider(provider_id: int, session: SessionDep, _user: RequireAuthDep) -> dict[str, str]:
    config = await SqlNotificationProviderRepository(session).get(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider = build_provider(config)
    if provider is None:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {config.provider}")
    try:
        await provider.test()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Provider test failed: {exc}") from exc
    return {"status": "sent"}


def _unique_copy_name(taken: set[str], base: str) -> str:
    candidate = f"{base} (copia)"
    n = 2
    while candidate in taken:
        candidate = f"{base} (copia {n})"
        n += 1
    return candidate


@router.post("/notification-providers/{provider_id}/duplicate", response_model=ProviderOut, status_code=201)
async def duplicate_provider(provider_id: int, session: SessionDep, _user: RequireAuthDep) -> ProviderOut:
    async with session.begin():
        repo = SqlNotificationProviderRepository(session)
        source = await repo.get(provider_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        taken = {p.name for p in await repo.list_all()}
        duplicate = await repo.create(
            NotificationProviderConfig(
                name=_unique_copy_name(taken, source.name),
                provider=source.provider,
                configuration=source.configuration,
                enabled=source.enabled,
            )
        )
    return ProviderOut.from_entity(duplicate)


# ── Canales (agrupación lógica) ──────────────────────────────────────────────


@router.get("/notification-channels", response_model=list[ChannelOut])
async def list_channels(session: SessionDep) -> list[ChannelOut]:
    channels = await SqlNotificationChannelRepository(session).list_all()
    return [ChannelOut.from_entity(c) for c in channels]


@router.post("/notification-channels", response_model=ChannelOut, status_code=201)
async def create_channel(body: ChannelIn, session: SessionDep, _user: RequireAuthDep) -> ChannelOut:
    async with session.begin():
        channel = await SqlNotificationChannelRepository(session).create(NotificationChannel(**body.model_dump()))
    return ChannelOut.from_entity(channel)


@router.patch("/notification-channels/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: int, body: ChannelPatch, session: SessionDep, _user: RequireAuthDep
) -> ChannelOut:
    async with session.begin():
        channel = await SqlNotificationChannelRepository(session).update(
            channel_id, body.model_dump(exclude_unset=True)
        )
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelOut.from_entity(channel)


@router.delete("/notification-channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: int, session: SessionDep, _user: RequireAuthDep) -> None:
    async with session.begin():
        deleted = await SqlNotificationChannelRepository(session).delete(channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")
