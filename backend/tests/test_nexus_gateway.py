"""Orquestación impura JenTastic-Nexus (ADR 0027): interruptor global (system_settings)
y escaneo de detección (relee chat_messages, nunca marca — ver docstring del módulo)."""

import asyncio
import uuid
from datetime import datetime, timezone

from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.ingest import IngestService
from noc.application.nexus_gateway import (
    MIN_SECONDS_BETWEEN_SCANS,
    NexusGateway,
    NexusScanCooldownError,
)

GW = "gw-test"
NODE_A = "!a1b2c3d4"
NODE_B = "!deadbeef"


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        self.sent.append((gateway_id, envelope))


def event(event_type: str, payload: dict, gateway_id: str = GW) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def seed_message(session_factory, node_id: str, text: str, gateway_id: str = GW) -> None:
    ingest = IngestService(session_factory)
    await ingest.handle_event(event("node.seen", {"node_id": node_id}, gateway_id))
    await ingest.handle_event(
        event("message.received", {"from_node_id": node_id, "text": text}, gateway_id)
    )


def jt_info(node_id: str, short: str, ver: str = "2.8.005.x", role: str = "MUTE") -> str:
    return f"JT INFO:\n{node_id} [{short}]\nVer: {ver}\nRole: {role}\nMAC: 00:00:00:00:00:00"


# ── Interruptor global ────────────────────────────────────────────────────


async def test_mode_disabled_by_default(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    assert await service.is_mode_enabled() is False


async def test_mode_toggle_persists(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    assert await service.is_mode_enabled() is True
    await service.set_mode_enabled(False, "admin")
    assert await service.is_mode_enabled() is False


# ── Escaneo (solo sugiere) ────────────────────────────────────────────────


async def test_scan_sends_broadcast_info_by_the_nexus_channel_auto_detected_by_gateway(
    session_factory,
):
    queue = FakeQueue()
    service = NexusGateway(session_factory, queue)
    await service.scan(GW, "operador", window_seconds=0)
    assert len(queue.sent) == 1
    gateway_id, envelope = queue.sent[0]
    assert gateway_id == GW
    assert envelope["command_type"] == "command.send_text"
    assert envelope["payload"]["text"] == "/nexus INFO"  # construido con el catálogo puro
    assert envelope["issued_by"] == "operador"
    assert envelope["payload"]["channel_name"] is None  # sin ajuste -> el gateway autodetecta


async def test_scan_returns_structured_candidates_from_chat_messages(session_factory):
    await seed_message(session_factory, NODE_A, jt_info(NODE_A, "ABMO", role="ROUTER"))
    await seed_message(session_factory, NODE_B, "🔴 " + jt_info(NODE_B, "OTR1"))

    service = NexusGateway(session_factory, FakeQueue())
    candidates = await service.scan(GW, "operador", window_seconds=0)

    by_id = {c.node_id: c for c in candidates}
    assert set(by_id) == {NODE_A, NODE_B}
    assert by_id[NODE_A].short_name == "ABMO"
    assert by_id[NODE_A].role == "ROUTER"
    assert by_id[NODE_A].marker is None
    assert by_id[NODE_B].marker == "🔴"
    assert all(not c.already_marked for c in candidates)


async def test_scan_ignores_unrelated_chat_traffic(session_factory):
    # Eco del propio comando + tráfico de otro sistema ajeno (mismo hallazgo
    # real de campo, ADR 0027 §0.2: comprobar contenido, no solo canal).
    await seed_message(session_factory, NODE_A, "/nexus INFO")
    await seed_message(session_factory, NODE_B, "🏓Pong!🏓\nhola")

    service = NexusGateway(session_factory, FakeQueue())
    candidates = await service.scan(GW, "operador", window_seconds=0)
    assert candidates == []


async def test_scan_marks_already_marked_nodes(session_factory):
    await seed_message(session_factory, NODE_A, jt_info(NODE_A, "ABMO"))
    async with session_factory() as session:
        await SqlNodeRepository(session).set_flag(NODE_A, "is_nexus", True)
        await session.commit()

    service = NexusGateway(session_factory, FakeQueue())
    [candidate] = await service.scan(GW, "operador", window_seconds=0)
    assert candidate.already_marked is True


async def test_scan_dedupes_by_node_id_keeping_latest(session_factory):
    await seed_message(session_factory, NODE_A, jt_info(NODE_A, "OLD1"))
    await seed_message(session_factory, NODE_A, jt_info(NODE_A, "NEW1"))

    service = NexusGateway(session_factory, FakeQueue())
    [candidate] = await service.scan(GW, "operador", window_seconds=0)
    assert candidate.short_name == "NEW1"  # más reciente primero (list_messages)


async def test_scan_does_not_mark_any_node(session_factory):
    """El escaneo SOLO sugiere — nunca escribe is_nexus (decisión repetida
    explícitamente por el usuario, ver docstring del módulo)."""
    await seed_message(session_factory, NODE_A, jt_info(NODE_A, "ABMO"))
    service = NexusGateway(session_factory, FakeQueue())
    await service.scan(GW, "operador", window_seconds=0)

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
    assert node is not None
    assert node.is_nexus is False


async def test_scan_rate_limited_per_gateway(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.scan(GW, "operador", window_seconds=0)
    try:
        await service.scan(GW, "operador", window_seconds=0)
    except NexusScanCooldownError as exc:
        assert 0 < exc.retry_after_seconds <= MIN_SECONDS_BETWEEN_SCANS
    else:
        raise AssertionError("se esperaba NexusScanCooldownError")


async def test_scan_rate_limit_is_per_gateway_not_global(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.scan(GW, "operador", window_seconds=0)
    await service.scan("gw-otra", "operador", window_seconds=0)  # no debe lanzar


async def test_scan_window_is_actually_awaited(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    loop = asyncio.get_running_loop()
    before = loop.time()
    await service.scan(GW, "operador", window_seconds=0.05)
    assert loop.time() - before >= 0.05


# ── Detección PASIVA (sin enviar nada) ───────────────────────────────────


async def test_passive_detection_ignores_traffic_while_mode_disabled(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": jt_info(NODE_A, "ABMO")}))
    assert await service.list_passive_candidates() == []


async def test_passive_detection_suggests_node_with_nexus_shaped_text(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": jt_info(NODE_A, "ABMO")}))

    [candidate] = await service.list_passive_candidates()
    assert candidate.node_id == NODE_A
    assert candidate.gateway_id == GW
    assert candidate.command == "INFO"
    assert candidate.match_count == 1
    assert candidate.already_marked is False


async def test_passive_detection_ignores_unrelated_traffic(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": "hola, buenas tardes"}))
    assert await service.list_passive_candidates() == []


async def test_passive_detection_accumulates_repeated_sightings(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    text = jt_info(NODE_A, "ABMO")
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": text}))
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": text}))

    [candidate] = await service.list_passive_candidates()
    assert candidate.match_count == 2


async def test_passive_detection_marks_already_marked_nodes(session_factory):
    await seed_message(session_factory, NODE_A, "hola")
    async with session_factory() as session:
        await SqlNodeRepository(session).set_flag(NODE_A, "is_nexus", True)
        await session.commit()

    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": jt_info(NODE_A, "ABMO")}))

    [candidate] = await service.list_passive_candidates()
    assert candidate.already_marked is True


async def test_passive_detection_dismiss_hides_candidate_and_future_sightings(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    text = jt_info(NODE_A, "ABMO")
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": text}))
    assert len(await service.list_passive_candidates()) == 1

    service.dismiss_passive_candidate(NODE_A)
    assert await service.list_passive_candidates() == []

    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": text}))
    assert await service.list_passive_candidates() == []  # sigue descartado, no reaparece


async def test_passive_detection_respects_setting_toggle(session_factory):
    from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository

    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    async with session_factory() as session:
        await SqlSystemSettingsRepository(session).upsert("nexus.passive_detection_enabled", False, "admin")
        await session.commit()

    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": jt_info(NODE_A, "ABMO")}))
    assert await service.list_passive_candidates() == []


async def test_passive_detection_never_marks_a_node_by_itself(session_factory):
    service = NexusGateway(session_factory, FakeQueue())
    await service.set_mode_enabled(True, "admin")
    await service.handle_event(event("message.received", {"from_node_id": NODE_A, "text": jt_info(NODE_A, "ABMO")}))

    async with session_factory() as session:
        node = await SqlNodeRepository(session).get(NODE_A)
    assert node is None or node.is_nexus is False
