import uuid
from datetime import datetime, timedelta, timezone

import pytest

from noc.application.dashboard import DashboardService, compute_status
from noc.application.ingest import IngestService
from noc.config import Settings

# ── Reglas de estado (función pura) ─────────────────────────────────────────

BASE = dict(
    nodes_total=100,
    offline_percent=0.0,
    gateways_total=1,
    gateways_healthy=1,
    low_battery_count=0,
    events_last_hour=50,
    offline_percent_warning=5,
    offline_percent_critical=20,
)


def status(**overrides):
    return compute_status(**{**BASE, **overrides})


def test_healthy():
    assert status() == "HEALTHY"


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateways_total": 2, "gateways_healthy": 1},
        {"offline_percent": 5.0},
        {"offline_percent": 12.0},
        {"low_battery_count": 1},
        {"nodes_total": 0, "events_last_hour": 0},  # red sin datos aún
        {"gateways_total": 0},
    ],
)
def test_warning(overrides):
    assert status(**overrides) == "WARNING"


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateways_healthy": 0},
        {"offline_percent": 25.0},
        {"events_last_hour": 0},  # ausencia prolongada de tráfico con nodos registrados
    ],
)
def test_critical(overrides):
    assert status(**overrides) == "CRITICAL"


def test_critical_takes_precedence_over_warning():
    assert status(gateways_healthy=0, low_battery_count=3) == "CRITICAL"


# ── Servicio completo contra base de datos ──────────────────────────────────


def make_event(event_type: str, payload: dict, ts: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-test",
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }


def make_settings(**overrides) -> Settings:
    overrides.setdefault("dashboard_cache_seconds", 0)
    return Settings(_env_file=None, **overrides)


async def seed(session_factory) -> None:
    ingest = IngestService(session_factory)
    now = datetime.now(timezone.utc)
    await ingest.handle_event(make_event("gateway.status", {"status": "connected", "transport": "simulated"}))
    # Nodo sano
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000001", "short_name": "OK", "snr": 5.0}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000001", "kind": "device", "battery_level": 90})
    )
    # Nodo con batería baja y SNR degradado
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000002", "short_name": "BAJO", "snr": -18.0}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000002", "kind": "device", "battery_level": 12})
    )
    # Nodo inactivo (visto hace 2 horas)
    await ingest.handle_event(
        make_event("node.seen", {"node_id": "!00000003", "short_name": "MUDO"}, now - timedelta(hours=2))
    )
    # Nodo con alimentación externa (excluido de la media de batería)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000004", "short_name": "ENCH"}))
    await ingest.handle_event(
        make_event("telemetry.received", {"node_id": "!00000004", "kind": "device", "battery_level": 101})
    )


async def test_summary_aggregates(session_factory):
    await seed(session_factory)
    service = DashboardService(session_factory, make_settings())
    s = await service.get_summary()

    assert s.nodes_total == 4
    assert s.nodes_online == 3  # el MUDO lleva 2h callado
    assert s.nodes_offline == 1
    assert s.gateways_total == 1 and s.gateways_connected == 1
    assert s.low_battery_count == 1
    assert s.avg_battery_percent == pytest.approx((90 + 12) / 2)  # 101 excluido
    assert s.avg_snr == pytest.approx((5.0 + -18.0) / 2)  # solo !00000001/!00000002 tienen snr
    assert s.avg_rssi is None  # ningún nodo sembrado trae rssi
    assert s.avg_channel_utilization is None  # ninguna telemetría sembrada trae channel_utilization
    assert s.events_last_hour == 3  # 3 telemetrías dentro de la última hora
    assert s.thresholds is not None and s.thresholds.low_battery_percent == 20
    # offline 25% > 20% crítico
    assert s.status == "CRITICAL"


async def test_critical_nodes_reasons_and_priority(session_factory):
    await seed(session_factory)
    service = DashboardService(session_factory, make_settings())
    s = await service.get_summary()

    by_id = {c.node_id: c for c in s.critical_nodes}
    assert set(by_id) == {"!00000002", "!00000003"}
    assert sorted(by_id["!00000002"].reasons) == ["degraded_snr", "low_battery"]
    assert by_id["!00000003"].reasons == ["inactive"]
    # El de 2 motivos va primero
    assert s.critical_nodes[0].node_id == "!00000002"


async def test_summary_cache(session_factory):
    await seed(session_factory)
    service = DashboardService(session_factory, make_settings(dashboard_cache_seconds=60))
    first = await service.get_summary()
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": "!00000005"}))
    cached = await service.get_summary()
    assert cached is first  # dentro del TTL no se recomputa
