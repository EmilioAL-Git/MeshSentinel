from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.notifications import CHANNEL_TYPES, build_channel
from noc.adapters.persistence.alert_repositories import (
    SqlAlertRepository,
    SqlAlertRuleRepository,
    SqlChannelRepository,
)
from noc.domain.alerts.entities import Alert, AlertRule, NotificationChannelConfig

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
    rule_type: Literal["low_battery", "node_offline", "snr_degraded", "gateway_disconnected"]
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    enabled: bool = True
    threshold: float | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    cooldown_seconds: int = Field(default=0, ge=0)
    params: dict[str, Any] = {}


class RulePatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    severity: Literal["INFO", "WARNING", "CRITICAL"] | None = None
    enabled: bool | None = None
    threshold: float | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    cooldown_seconds: int | None = Field(default=None, ge=0)
    params: dict[str, Any] | None = None


class RuleOut(RuleIn):
    id: int
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, r: AlertRule) -> "RuleOut":
        return cls(**{f: getattr(r, f) for f in cls.model_fields})


class ChannelIn(BaseModel):
    name: str = Field(max_length=128)
    channel_type: Literal["webhook", "ntfy"]
    config: dict[str, Any]
    enabled: bool = True


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ChannelOut(ChannelIn):
    id: int

    @classmethod
    def from_entity(cls, c: NotificationChannelConfig) -> "ChannelOut":
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
async def create_rule(body: RuleIn, session: SessionDep) -> RuleOut:
    async with session.begin():
        rule = await SqlAlertRuleRepository(session).create(AlertRule(**body.model_dump()))
    return RuleOut.from_entity(rule)


@router.patch("/alert-rules/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, body: RulePatch, session: SessionDep) -> RuleOut:
    changes = body.model_dump(exclude_unset=True)
    async with session.begin():
        rule = await SqlAlertRuleRepository(session).update(rule_id, changes)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RuleOut.from_entity(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, session: SessionDep) -> None:
    async with session.begin():
        deleted = await SqlAlertRuleRepository(session).delete(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")


# ── Canales ──────────────────────────────────────────────────────────────────


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(session: SessionDep) -> list[ChannelOut]:
    channels = await SqlChannelRepository(session).list_all()
    return [ChannelOut.from_entity(c) for c in channels]


@router.post("/channels", response_model=ChannelOut, status_code=201)
async def create_channel(body: ChannelIn, session: SessionDep) -> ChannelOut:
    if body.channel_type not in CHANNEL_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown channel_type: {body.channel_type}")
    async with session.begin():
        channel = await SqlChannelRepository(session).create(
            NotificationChannelConfig(**body.model_dump())
        )
    return ChannelOut.from_entity(channel)


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: int, body: ChannelPatch, session: SessionDep) -> ChannelOut:
    async with session.begin():
        channel = await SqlChannelRepository(session).update(channel_id, body.model_dump(exclude_unset=True))
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelOut.from_entity(channel)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: int, session: SessionDep) -> None:
    async with session.begin():
        deleted = await SqlChannelRepository(session).delete(channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: int, session: SessionDep) -> dict[str, str]:
    config = await SqlChannelRepository(session).get(channel_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel = build_channel(config)
    if channel is None:
        raise HTTPException(status_code=422, detail=f"Unknown channel_type: {config.channel_type}")
    from datetime import timezone

    test_alert = Alert(
        rule_id=0,
        rule_name="Prueba de canal",
        subject_type="system",
        subject_id="noc",
        severity="INFO",
        message=f"Mensaje de prueba del canal '{config.name}' — Meshtastic NOC",
        fired_at=datetime.now(timezone.utc),
    )
    try:
        await channel.send(test_alert, "test")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Channel test failed: {exc}") from exc
    return {"status": "sent"}
