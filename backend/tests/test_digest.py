from datetime import datetime, timedelta, timezone

from noc.application.dashboard import DashboardSummary
from noc.application.digest import build_digest_message, is_due
from noc.application.stats import StatRecord

NOW = datetime(2026, 10, 3, 8, 0, 20, tzinfo=timezone.utc)


def _summary(status="HEALTHY") -> DashboardSummary:
    return DashboardSummary(
        status=status, generated_at=NOW, nodes_total=10, nodes_online=8, nodes_offline=2,
        offline_percent=20.0, gateways_total=2, gateways_connected=1, low_battery_count=3,
        avg_battery_percent=70, avg_seconds_since_last_seen=60, events_last_hour=5,
    )


def test_is_due_only_at_configured_hour_and_period():
    kw = {"period_hours": 24, "hour_utc": 8}
    assert is_due(now=NOW, last_sent=None, **kw)
    assert not is_due(now=NOW.replace(hour=9), last_sent=None, **kw)
    assert not is_due(now=NOW, last_sent=NOW - timedelta(hours=2), **kw)  # ya enviado hoy
    # Ayer a las 08:00:30: el margen de 10 min permite el de hoy a las 08:00:20
    assert is_due(now=NOW, last_sent=NOW - timedelta(hours=24) + timedelta(seconds=10), **kw)
    assert not is_due(now=NOW, last_sent=None, period_hours=0, hour_utc=8)  # desactivado
    # Semanal: 3 días después aún no
    assert not is_due(now=NOW, last_sent=NOW - timedelta(days=3), period_hours=168, hour_utc=8)


def test_message_contents_and_markdown_safety():
    rec = StatRecord("uptime", "Más uptime", "⏱", "h", "!1", "A_B", "Nodo *raro* [x]", 12.5)
    msg = build_digest_message(
        dashboard=_summary("WARNING"), records=[rec], new_nodes=4, alerts_fired=7,
        alerts_critical=2, alerts_active=3, hours=24, now=NOW,
    )
    assert msg.kind == "digest" and msg.severity == "WARNING"
    assert "8/10 nodos en línea" in msg.body
    assert "Nodos nuevos: 4" in msg.body
    assert "7 disparadas (2 críticas) · 3 activas" in msg.body
    assert "Batería baja: 3" in msg.body
    assert "*" not in msg.body and "[" not in msg.body  # no rompe el Markdown de Telegram
    assert msg.title.endswith("24 h")


def test_traceroute_registry_and_validation():
    import pytest

    from noc.application.admin.registry import OPERATIONS, validate_operation

    spec = OPERATIONS["traceroute.run"]
    assert spec.kind == "get" and not spec.allow_bulk and not spec.requires_confirmation
    assert validate_operation("traceroute.run", {}) == {"hop_limit": 5}
    assert validate_operation("traceroute.run", {"hop_limit": "3"}) == {"hop_limit": 3}
    for bad in ({"hop_limit": 0}, {"hop_limit": 8}, {"hop_limit": "x"}, {"foo": 1}):
        with pytest.raises(ValueError):
            validate_operation("traceroute.run", bad)
