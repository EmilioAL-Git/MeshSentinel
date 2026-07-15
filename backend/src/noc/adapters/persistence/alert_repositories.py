from dataclasses import fields
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import (
    AlertModel,
    AlertRuleChannelModel,
    AlertRuleModel,
    GroupMemberModel,
    NotificationChannelModel,
    NotificationChannelProviderModel,
    NotificationProviderModel,
)
from noc.domain.alerts.entities import (
    ACTIVE_STATUSES,
    Alert,
    AlertRule,
    NotificationChannel,
    NotificationProviderConfig,
)


def _rule_entity(m: AlertRuleModel) -> AlertRule:
    data = {f.name: getattr(m, f.name) for f in fields(AlertRule) if f.name != "channel_ids"}
    return AlertRule(**data)


def _alert_entity(m: AlertModel) -> Alert:
    return Alert(**{f.name: getattr(m, f.name) for f in fields(Alert)})


def _provider_entity(m: NotificationProviderModel) -> NotificationProviderConfig:
    return NotificationProviderConfig(
        **{f.name: getattr(m, f.name) for f in fields(NotificationProviderConfig)}
    )


def _channel_entity(m: NotificationChannelModel) -> NotificationChannel:
    data = {f.name: getattr(m, f.name) for f in fields(NotificationChannel) if f.name != "provider_ids"}
    return NotificationChannel(**data)


class SqlAlertRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _attach_channel_ids(self, rules: list[AlertRule]) -> list[AlertRule]:
        if not rules:
            return rules
        ids = [r.id for r in rules if r.id is not None]
        rows = await self._session.execute(
            select(AlertRuleChannelModel.rule_id, AlertRuleChannelModel.channel_id).where(
                AlertRuleChannelModel.rule_id.in_(ids)
            )
        )
        by_rule: dict[int, list[int]] = {}
        for rule_id, channel_id in rows.all():
            by_rule.setdefault(rule_id, []).append(channel_id)
        for rule in rules:
            rule.channel_ids = by_rule.get(rule.id, [])
        return rules

    async def list_all(self) -> list[AlertRule]:
        rows = await self._session.scalars(select(AlertRuleModel).order_by(AlertRuleModel.id))
        return await self._attach_channel_ids([_rule_entity(r) for r in rows])

    async def list_enabled(self) -> list[AlertRule]:
        # Sin channel_ids a propósito: la usa solo el bucle de evaluación
        # (engine.py), que nunca enruta notificaciones — el dispatcher
        # resuelve channel_ids con get() para la única regla que dispara.
        rows = await self._session.scalars(
            select(AlertRuleModel).where(AlertRuleModel.enabled.is_(True)).order_by(AlertRuleModel.id)
        )
        return [_rule_entity(r) for r in rows]

    async def get(self, rule_id: int) -> AlertRule | None:
        m = await self._session.get(AlertRuleModel, rule_id)
        if m is None:
            return None
        rule = _rule_entity(m)
        await self._attach_channel_ids([rule])
        return rule

    async def list_channel_ids(self, rule_id: int) -> list[int]:
        rows = await self._session.scalars(
            select(AlertRuleChannelModel.channel_id).where(AlertRuleChannelModel.rule_id == rule_id)
        )
        return list(rows)

    async def set_channels(self, rule_id: int, channel_ids: list[int]) -> None:
        await self._session.execute(delete(AlertRuleChannelModel).where(AlertRuleChannelModel.rule_id == rule_id))
        for channel_id in dict.fromkeys(channel_ids):  # dedupe conservando orden
            self._session.add(AlertRuleChannelModel(rule_id=rule_id, channel_id=channel_id))
        await self._session.flush()

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
            group_id=rule.group_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(m)
        await self._session.flush()
        if rule.channel_ids:
            await self.set_channels(m.id, rule.channel_ids)
        return await self.get(m.id)

    async def update(self, rule_id: int, changes: dict) -> AlertRule | None:
        m = await self._session.get(AlertRuleModel, rule_id)
        if m is None:
            return None
        channel_ids = changes.pop("channel_ids", None)
        for key, value in changes.items():
            setattr(m, key, value)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        if channel_ids is not None:
            await self.set_channels(rule_id, channel_ids)
        return await self.get(rule_id)

    async def delete(self, rule_id: int) -> bool:
        m = await self._session.get(AlertRuleModel, rule_id)
        if m is None:
            return False
        await self._session.execute(delete(AlertRuleChannelModel).where(AlertRuleChannelModel.rule_id == rule_id))
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


class SqlNotificationProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[NotificationProviderConfig]:
        rows = await self._session.scalars(select(NotificationProviderModel).order_by(NotificationProviderModel.id))
        return [_provider_entity(r) for r in rows]

    async def list_enabled(self) -> list[NotificationProviderConfig]:
        rows = await self._session.scalars(
            select(NotificationProviderModel).where(NotificationProviderModel.enabled.is_(True))
        )
        return [_provider_entity(r) for r in rows]

    async def list_by_ids(self, provider_ids: list[int]) -> list[NotificationProviderConfig]:
        if not provider_ids:
            return []
        rows = await self._session.scalars(
            select(NotificationProviderModel).where(NotificationProviderModel.id.in_(provider_ids))
        )
        return [_provider_entity(r) for r in rows]

    async def get(self, provider_id: int) -> NotificationProviderConfig | None:
        m = await self._session.get(NotificationProviderModel, provider_id)
        return _provider_entity(m) if m else None

    async def create(self, provider: NotificationProviderConfig) -> NotificationProviderConfig:
        now = datetime.now(timezone.utc)
        m = NotificationProviderModel(
            name=provider.name,
            provider=provider.provider,
            configuration=provider.configuration,
            enabled=provider.enabled,
            created_at=now,
            updated_at=now,
        )
        self._session.add(m)
        await self._session.flush()
        return _provider_entity(m)

    async def update(self, provider_id: int, changes: dict) -> NotificationProviderConfig | None:
        m = await self._session.get(NotificationProviderModel, provider_id)
        if m is None:
            return None
        for key, value in changes.items():
            setattr(m, key, value)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _provider_entity(m)

    async def delete(self, provider_id: int) -> bool:
        m = await self._session.get(NotificationProviderModel, provider_id)
        if m is None:
            return False
        await self._session.execute(
            delete(NotificationChannelProviderModel).where(NotificationChannelProviderModel.provider_id == provider_id)
        )
        await self._session.delete(m)
        await self._session.flush()
        return True


class SqlNotificationChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _attach_provider_ids(self, channels: list[NotificationChannel]) -> list[NotificationChannel]:
        if not channels:
            return channels
        ids = [c.id for c in channels if c.id is not None]
        rows = await self._session.execute(
            select(NotificationChannelProviderModel.channel_id, NotificationChannelProviderModel.provider_id).where(
                NotificationChannelProviderModel.channel_id.in_(ids)
            )
        )
        by_channel: dict[int, list[int]] = {}
        for channel_id, provider_id in rows.all():
            by_channel.setdefault(channel_id, []).append(provider_id)
        for channel in channels:
            channel.provider_ids = by_channel.get(channel.id, [])
        return channels

    async def list_all(self) -> list[NotificationChannel]:
        rows = await self._session.scalars(select(NotificationChannelModel).order_by(NotificationChannelModel.id))
        return await self._attach_provider_ids([_channel_entity(r) for r in rows])

    async def get(self, channel_id: int) -> NotificationChannel | None:
        m = await self._session.get(NotificationChannelModel, channel_id)
        if m is None:
            return None
        channel = _channel_entity(m)
        await self._attach_provider_ids([channel])
        return channel

    async def list_provider_ids(self, channel_id: int) -> list[int]:
        rows = await self._session.scalars(
            select(NotificationChannelProviderModel.provider_id).where(
                NotificationChannelProviderModel.channel_id == channel_id
            )
        )
        return list(rows)

    async def set_providers(self, channel_id: int, provider_ids: list[int]) -> None:
        await self._session.execute(
            delete(NotificationChannelProviderModel).where(NotificationChannelProviderModel.channel_id == channel_id)
        )
        for provider_id in dict.fromkeys(provider_ids):
            self._session.add(NotificationChannelProviderModel(channel_id=channel_id, provider_id=provider_id))
        await self._session.flush()

    async def list_providers_for_channels(self, channel_ids: list[int]) -> list[NotificationProviderConfig]:
        """Unión deduplicada de proveedores (por id) de los canales dados —
        para no enviar dos veces si un proveedor está en 2 canales de la
        misma regla."""
        if not channel_ids:
            return []
        provider_id_rows = await self._session.scalars(
            select(NotificationChannelProviderModel.provider_id)
            .where(NotificationChannelProviderModel.channel_id.in_(channel_ids))
            .distinct()
        )
        provider_ids = list(provider_id_rows)
        if not provider_ids:
            return []
        rows = await self._session.scalars(
            select(NotificationProviderModel).where(
                NotificationProviderModel.id.in_(provider_ids),
                NotificationProviderModel.enabled.is_(True),
            )
        )
        return [_provider_entity(r) for r in rows]

    async def create(self, channel: NotificationChannel) -> NotificationChannel:
        now = datetime.now(timezone.utc)
        m = NotificationChannelModel(
            name=channel.name,
            description=channel.description,
            created_at=now,
            updated_at=now,
        )
        self._session.add(m)
        await self._session.flush()
        if channel.provider_ids:
            await self.set_providers(m.id, channel.provider_ids)
        return await self.get(m.id)

    async def update(self, channel_id: int, changes: dict) -> NotificationChannel | None:
        m = await self._session.get(NotificationChannelModel, channel_id)
        if m is None:
            return None
        provider_ids = changes.pop("provider_ids", None)
        for key, value in changes.items():
            setattr(m, key, value)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        if provider_ids is not None:
            await self.set_providers(channel_id, provider_ids)
        return await self.get(channel_id)

    async def delete(self, channel_id: int) -> bool:
        m = await self._session.get(NotificationChannelModel, channel_id)
        if m is None:
            return False
        await self._session.execute(
            delete(NotificationChannelProviderModel).where(NotificationChannelProviderModel.channel_id == channel_id)
        )
        await self._session.execute(delete(AlertRuleChannelModel).where(AlertRuleChannelModel.channel_id == channel_id))
        await self._session.delete(m)
        await self._session.flush()
        return True
