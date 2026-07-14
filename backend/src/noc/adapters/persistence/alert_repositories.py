from dataclasses import fields
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import (
    AlertModel,
    AlertRuleModel,
    GroupMemberModel,
    NotificationChannelModel,
)
from noc.domain.alerts.entities import (
    ACTIVE_STATUSES,
    Alert,
    AlertRule,
    NotificationChannelConfig,
)


def _rule_entity(m: AlertRuleModel) -> AlertRule:
    return AlertRule(**{f.name: getattr(m, f.name) for f in fields(AlertRule)})


def _alert_entity(m: AlertModel) -> Alert:
    return Alert(**{f.name: getattr(m, f.name) for f in fields(Alert)})


def _channel_entity(m: NotificationChannelModel) -> NotificationChannelConfig:
    return NotificationChannelConfig(
        **{f.name: getattr(m, f.name) for f in fields(NotificationChannelConfig)}
    )


class SqlAlertRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[AlertRule]:
        rows = await self._session.scalars(select(AlertRuleModel).order_by(AlertRuleModel.id))
        return [_rule_entity(r) for r in rows]

    async def list_enabled(self) -> list[AlertRule]:
        rows = await self._session.scalars(
            select(AlertRuleModel).where(AlertRuleModel.enabled.is_(True)).order_by(AlertRuleModel.id)
        )
        return [_rule_entity(r) for r in rows]

    async def get(self, rule_id: int) -> AlertRule | None:
        m = await self._session.get(AlertRuleModel, rule_id)
        return _rule_entity(m) if m else None

    async def count(self) -> int:
        rows = await self._session.scalars(select(AlertRuleModel.id))
        return len(list(rows))

    async def create(self, rule: AlertRule) -> AlertRule:
        now = datetime.now(timezone.utc)
        m = AlertRuleModel(
            name=rule.name,
            rule_type=rule.rule_type,
            severity=rule.severity,
            enabled=rule.enabled,
            threshold=rule.threshold,
            duration_seconds=rule.duration_seconds,
            cooldown_seconds=rule.cooldown_seconds,
            params=rule.params,
            created_at=now,
            updated_at=now,
        )
        self._session.add(m)
        await self._session.flush()
        return _rule_entity(m)

    async def update(self, rule_id: int, changes: dict) -> AlertRule | None:
        m = await self._session.get(AlertRuleModel, rule_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _rule_entity(m)

    async def delete(self, rule_id: int) -> bool:
        m = await self._session.get(AlertRuleModel, rule_id)
        if m is None:
            return False
        await self._session.delete(m)
        await self._session.flush()
        return True


class SqlAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_alerts(self, status: str | None, limit: int) -> list[Alert]:
        stmt = select(AlertModel).order_by(AlertModel.fired_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(AlertModel.status == status)
        rows = await self._session.scalars(stmt)
        return [_alert_entity(r) for r in rows]

    async def list_active(self) -> list[Alert]:
        rows = await self._session.scalars(
            select(AlertModel).where(AlertModel.status.in_(ACTIVE_STATUSES))
        )
        return [_alert_entity(r) for r in rows]

    async def active_counts(self, group_id: int | None = None) -> dict[str, int]:
        """Agregados de alertas activas para HUD/insignias (hardening): los
        contadores "siempre visibles" nunca deben derivar de listas truncadas.

        Con `group_id`, replica EXACTAMENTE la semántica del escopado de la
        UI (`scopeAlertsToGroup`): alertas de sujeto no-nodo siempre dentro;
        las CRITICAL de nodos fuera del grupo también cuentan (nunca se
        ocultan, principio v0.7 §2.1)."""
        stmt = (
            select(AlertModel.status, AlertModel.severity, func.count())
            .where(AlertModel.status.in_(ACTIVE_STATUSES))
            .group_by(AlertModel.status, AlertModel.severity)
        )
        if group_id is not None:
            members = select(GroupMemberModel.node_id).where(
                GroupMemberModel.group_id == group_id
            )
            stmt = stmt.where(
                or_(
                    AlertModel.subject_type != "node",
                    AlertModel.severity == "CRITICAL",
                    AlertModel.subject_id.in_(members),
                )
            )
        counts = {"active": 0, "firing": 0, "acknowledged": 0, "critical_active": 0}
        for status, severity, n in (await self._session.execute(stmt)).all():
            counts["active"] += n
            counts[status] = counts.get(status, 0) + n
            if severity == "CRITICAL":
                counts["critical_active"] += n
        return counts

    async def get(self, alert_id: int) -> Alert | None:
        m = await self._session.get(AlertModel, alert_id)
        return _alert_entity(m) if m else None

    async def create(self, alert: Alert) -> Alert:
        m = AlertModel(
            rule_id=alert.rule_id,
            rule_name=alert.rule_name,
            subject_type=alert.subject_type,
            subject_id=alert.subject_id,
            severity=alert.severity,
            status=alert.status,
            message=alert.message,
            correlation_key=alert.correlation_key,
            fired_at=alert.fired_at or datetime.now(timezone.utc),
            last_notified_at=alert.last_notified_at,
        )
        self._session.add(m)
        await self._session.flush()
        return _alert_entity(m)

    async def acknowledge(self, alert_id: int, by: str) -> Alert | None:
        m = await self._session.get(AlertModel, alert_id)
        if m is None or m.status not in ACTIVE_STATUSES:
            return None
        if m.status == "firing":
            m.status = "acknowledged"
            m.acknowledged_at = datetime.now(timezone.utc)
            m.acknowledged_by = by
            await self._session.flush()
        return _alert_entity(m)

    async def resolve(self, alert_id: int, now: datetime) -> Alert | None:
        m = await self._session.get(AlertModel, alert_id)
        if m is None:
            return None
        m.status = "resolved"
        m.resolved_at = now
        await self._session.flush()
        return _alert_entity(m)

    async def mark_notified(self, alert_id: int, now: datetime) -> None:
        m = await self._session.get(AlertModel, alert_id)
        if m is not None:
            m.last_notified_at = now
            await self._session.flush()


class SqlChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[NotificationChannelConfig]:
        rows = await self._session.scalars(select(NotificationChannelModel).order_by(NotificationChannelModel.id))
        return [_channel_entity(r) for r in rows]

    async def list_enabled(self) -> list[NotificationChannelConfig]:
        rows = await self._session.scalars(
            select(NotificationChannelModel).where(NotificationChannelModel.enabled.is_(True))
        )
        return [_channel_entity(r) for r in rows]

    async def get(self, channel_id: int) -> NotificationChannelConfig | None:
        m = await self._session.get(NotificationChannelModel, channel_id)
        return _channel_entity(m) if m else None

    async def create(self, channel: NotificationChannelConfig) -> NotificationChannelConfig:
        m = NotificationChannelModel(
            name=channel.name,
            channel_type=channel.channel_type,
            config=channel.config,
            enabled=channel.enabled,
        )
        self._session.add(m)
        await self._session.flush()
        return _channel_entity(m)

    async def update(self, channel_id: int, changes: dict) -> NotificationChannelConfig | None:
        m = await self._session.get(NotificationChannelModel, channel_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        await self._session.flush()
        return _channel_entity(m)

    async def delete(self, channel_id: int) -> bool:
        m = await self._session.get(NotificationChannelModel, channel_id)
        if m is None:
            return False
        await self._session.delete(m)
        await self._session.flush()
        return True
