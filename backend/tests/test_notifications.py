"""Notificaciones multi-proveedor: proveedores (integraciones), canales
lógicos y el dispatcher que los enruta. Ver docs/design y ADR de
notificaciones multi-proveedor."""

from datetime import datetime, timezone

from noc.adapters.api.routers.alerts import ProviderPatch, duplicate_provider, update_provider
from noc.adapters.notifications import PROVIDERS, build_provider
from noc.adapters.notifications.ntfy import NtfyProvider
from noc.adapters.notifications.telegram import TelegramProvider
from noc.adapters.notifications.webhook import WebhookProvider
from noc.adapters.persistence.alert_repositories import (
    SqlAlertRuleRepository,
    SqlNotificationChannelRepository,
    SqlNotificationProviderRepository,
)
from noc.application.alerting.dispatcher import NotificationDispatcher
from noc.application.alerting.engine import AlertTransition
from noc.application.alerting.message import render_message
from noc.domain.alerts.entities import Alert, AlertRule, NotificationChannel, NotificationProviderConfig


def make_alert(**overrides) -> Alert:
    defaults = dict(
        id=1,
        rule_id=1,
        rule_name="Batería baja",
        subject_type="node",
        subject_id="!00000002",
        severity="WARNING",
        message="Batería al 8%",
        fired_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Alert(**defaults)


# ── validate() por proveedor ─────────────────────────────────────────────────


def test_webhook_validate_rejects_incomplete_config():
    assert WebhookProvider({}).validate() == ["Falta 'url'"]
    assert WebhookProvider({"url": "https://example.com/hook"}).validate() == []


def test_ntfy_validate_rejects_incomplete_config():
    assert NtfyProvider({}).validate() == ["Falta 'topic'"]
    assert NtfyProvider({"topic": "noc"}).validate() == []


def test_telegram_validate_rejects_incomplete_config():
    assert TelegramProvider({}).validate() == ["Falta 'bot_token'", "Falta 'chat_id'"]
    assert TelegramProvider({"bot_token": "t", "chat_id": "1"}).validate() == []


def test_build_provider_uses_registry():
    assert "telegram" in PROVIDERS
    provider = build_provider(NotificationProviderConfig(name="x", provider="telegram", configuration={}))
    assert isinstance(provider, TelegramProvider)
    assert build_provider(NotificationProviderConfig(name="x", provider="unknown", configuration={})) is None


# ── Canales lógicos y su tabla puente ────────────────────────────────────────


async def test_channel_crud_and_provider_membership(session_factory):
    async with session_factory() as session, session.begin():
        providers = SqlNotificationProviderRepository(session)
        p1 = await providers.create(NotificationProviderConfig(name="p1", provider="ntfy", configuration={"topic": "a"}))
        p2 = await providers.create(NotificationProviderConfig(name="p2", provider="ntfy", configuration={"topic": "b"}))

        channels = SqlNotificationChannelRepository(session)
        channel = await channels.create(NotificationChannel(name="Operadores", provider_ids=[p1.id, p2.id]))
        assert sorted(channel.provider_ids) == sorted([p1.id, p2.id])

    async with session_factory() as session:
        channels = SqlNotificationChannelRepository(session)
        fetched = await channels.get(channel.id)
        assert sorted(fetched.provider_ids) == sorted([p1.id, p2.id])

    async with session_factory() as session, session.begin():
        channels = SqlNotificationChannelRepository(session)
        updated = await channels.update(channel.id, {"provider_ids": [p1.id]})
        assert updated.provider_ids == [p1.id]

    async with session_factory() as session, session.begin():
        deleted = await SqlNotificationChannelRepository(session).delete(channel.id)
        assert deleted is True


async def test_list_providers_for_channels_dedupes(session_factory):
    async with session_factory() as session, session.begin():
        providers = SqlNotificationProviderRepository(session)
        p1 = await providers.create(NotificationProviderConfig(name="p1", provider="ntfy", configuration={"topic": "a"}))
        p2 = await providers.create(NotificationProviderConfig(name="p2", provider="ntfy", configuration={"topic": "b"}))
        # p3 disabled: nunca debe aparecer en la unión
        p3 = await providers.create(
            NotificationProviderConfig(name="p3", provider="ntfy", configuration={"topic": "c"}, enabled=False)
        )

        channels = SqlNotificationChannelRepository(session)
        c1 = await channels.create(NotificationChannel(name="Operadores", provider_ids=[p1.id, p2.id]))
        c2 = await channels.create(NotificationChannel(name="Guardia", provider_ids=[p2.id, p3.id]))

    async with session_factory() as session:
        union = await SqlNotificationChannelRepository(session).list_providers_for_channels([c1.id, c2.id])
    assert sorted(u.id for u in union) == sorted([p1.id, p2.id])


# ── set_channels en reglas ────────────────────────────────────────────────────


async def test_rule_set_channels_roundtrip(session_factory):
    async with session_factory() as session, session.begin():
        channels = SqlNotificationChannelRepository(session)
        c1 = await channels.create(NotificationChannel(name="Operadores"))
        c2 = await channels.create(NotificationChannel(name="Guardia"))

        rules = SqlAlertRuleRepository(session)
        rule = await rules.create(AlertRule(name="R", rule_type="low_battery", severity="WARNING", threshold=20))
        assert rule.channel_ids == []
        await rules.set_channels(rule.id, [c1.id, c2.id])

    async with session_factory() as session:
        fetched = await SqlAlertRuleRepository(session).get(rule.id)
        assert sorted(fetched.channel_ids) == sorted([c1.id, c2.id])

    async with session_factory() as session, session.begin():
        rules = SqlAlertRuleRepository(session)
        updated = await rules.update(rule.id, {"channel_ids": [c1.id]})
        assert updated.channel_ids == [c1.id]


async def test_create_rule_with_channel_ids(session_factory):
    async with session_factory() as session, session.begin():
        channel = await SqlNotificationChannelRepository(session).create(NotificationChannel(name="Operadores"))
        rule = await SqlAlertRuleRepository(session).create(
            AlertRule(name="R2", rule_type="low_battery", severity="WARNING", channel_ids=[channel.id])
        )
        assert rule.channel_ids == [channel.id]


# ── Dispatcher: fallback vs. enrutado por canal ──────────────────────────────


class FakeProvider:
    sent: list = []

    def __init__(self, configuration):
        self._configuration = configuration

    def validate(self):
        return []

    async def send(self, message):
        FakeProvider.sent.append((self._configuration.get("label"), message))

    async def test(self):
        pass


async def test_dispatcher_fallback_broadcasts_to_all_enabled(session_factory, monkeypatch):
    import noc.application.alerting.dispatcher as dispatcher_module

    monkeypatch.setitem(PROVIDERS, "fake", FakeProvider)
    FakeProvider.sent = []

    async with session_factory() as session, session.begin():
        providers = SqlNotificationProviderRepository(session)
        await providers.create(NotificationProviderConfig(name="A", provider="fake", configuration={"label": "A"}))
        await providers.create(NotificationProviderConfig(name="B", provider="fake", configuration={"label": "B"}))
        await providers.create(
            NotificationProviderConfig(name="C-disabled", provider="fake", configuration={"label": "C"}, enabled=False)
        )
        rule = await SqlAlertRuleRepository(session).create(
            AlertRule(name="Sin canales", rule_type="low_battery", severity="WARNING")
        )

    alert = make_alert(rule_id=rule.id)
    dispatcher = dispatcher_module.NotificationDispatcher(session_factory)
    await dispatcher(AlertTransition(kind="fired", alert=alert))

    labels = sorted(label for label, _ in FakeProvider.sent)
    assert labels == ["A", "B"]


async def test_dispatcher_routes_only_to_assigned_channel_providers(session_factory, monkeypatch):
    monkeypatch.setitem(PROVIDERS, "fake", FakeProvider)
    FakeProvider.sent = []

    async with session_factory() as session, session.begin():
        providers = SqlNotificationProviderRepository(session)
        p_in = await providers.create(NotificationProviderConfig(name="In", provider="fake", configuration={"label": "In"}))
        await providers.create(NotificationProviderConfig(name="Out", provider="fake", configuration={"label": "Out"}))

        channel = await SqlNotificationChannelRepository(session).create(
            NotificationChannel(name="Operadores", provider_ids=[p_in.id])
        )
        rule = await SqlAlertRuleRepository(session).create(
            AlertRule(name="Con canal", rule_type="low_battery", severity="WARNING", channel_ids=[channel.id])
        )

    alert = make_alert(rule_id=rule.id)
    dispatcher = NotificationDispatcher(session_factory)
    await dispatcher(AlertTransition(kind="fired", alert=alert))

    labels = [label for label, _ in FakeProvider.sent]
    assert labels == ["In"]


async def test_dispatcher_dedupes_provider_shared_by_two_channels(session_factory, monkeypatch):
    monkeypatch.setitem(PROVIDERS, "fake", FakeProvider)
    FakeProvider.sent = []

    async with session_factory() as session, session.begin():
        providers = SqlNotificationProviderRepository(session)
        shared = await providers.create(
            NotificationProviderConfig(name="Shared", provider="fake", configuration={"label": "Shared"})
        )
        channels = SqlNotificationChannelRepository(session)
        c1 = await channels.create(NotificationChannel(name="Operadores", provider_ids=[shared.id]))
        c2 = await channels.create(NotificationChannel(name="Guardia", provider_ids=[shared.id]))
        rule = await SqlAlertRuleRepository(session).create(
            AlertRule(name="Doble canal", rule_type="low_battery", severity="WARNING", channel_ids=[c1.id, c2.id])
        )

    alert = make_alert(rule_id=rule.id)
    dispatcher = NotificationDispatcher(session_factory)
    await dispatcher(AlertTransition(kind="fired", alert=alert))

    assert len(FakeProvider.sent) == 1


def test_render_message_shape():
    alert = make_alert()
    message = render_message(alert, "fired")
    assert message.severity == "WARNING"
    assert message.kind == "fired"
    assert message.subject_label == "node:!00000002"
    assert "Batería baja" in message.title


# ── Rutas del router llamadas directamente (mismo patrón que el resto de este
# archivo: sin infraestructura HTTP, la sesión de FastAPI nunca hace begin()
# de antemano — session_factory() sin `session.begin()` la reproduce fiel) ──


async def test_update_provider_with_configuration_does_not_double_begin(session_factory):
    async with session_factory() as session, session.begin():
        p = await SqlNotificationProviderRepository(session).create(
            NotificationProviderConfig(name="p1", provider="ntfy", configuration={"topic": "a"})
        )

    async with session_factory() as session:
        updated = await update_provider(
            p.id, ProviderPatch(configuration={"topic": "b"}), session, None
        )
    assert updated.configuration == {"topic": "b"}


async def test_duplicate_provider_twice_gets_distinct_names(session_factory):
    async with session_factory() as session, session.begin():
        p = await SqlNotificationProviderRepository(session).create(
            NotificationProviderConfig(name="Ops", provider="ntfy", configuration={"topic": "a"})
        )

    async with session_factory() as session:
        first = await duplicate_provider(p.id, session, None)
    async with session_factory() as session:
        second = await duplicate_provider(p.id, session, None)

    assert {first.name, second.name} == {"Ops (copia)", "Ops (copia 2)"}
