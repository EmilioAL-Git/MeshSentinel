"""Cola persistente de operaciones JenTastic-Nexus (ADR 0027 §4): scheduler
con el espaciado del núcleo puro (pacing.py), correlación de respuestas por
`message.received` (el gateway nunca reporta resultado) y vigilante de
sin-respuesta. Tiempo controlado explícitamente (mismo criterio que
test_nexus.py de pacing.py) en vez de dormir de verdad."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from noc.application.nexus.builder import NexusCommandError
from noc.application.nexus_operations import (
    DEFAULT_RESPONSE_WINDOW_SECONDS,
    NexusOperationService,
    NexusTargetError,
)

GW = "gw-test"
T0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        self.sent.append((gateway_id, envelope))


def message_event(from_node_id: str, text: str, gateway_id: str = GW) -> dict:
    return {
        "schema_version": 1,
        "event_type": "message.received",
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"from_node_id": from_node_id, "text": text},
    }


# ── Creación ─────────────────────────────────────────────────────────────


async def test_create_persists_pending_with_built_text(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    op = await service.create(GW, "STATS", [], "broadcast", None, "operador")
    assert op.status == "pending"
    assert op.text == "/nexus STATS"
    assert op.gateway_id == GW
    assert op.created_by == "operador"
    assert not op.destructive


async def test_create_node_target_builds_nexus_node_prefix(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    op = await service.create(GW, "INFO", [], "node", "N018", "operador")
    assert op.text == "/nexus-node N018 INFO"


async def test_create_destructive_flagged(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    op = await service.create(GW, "REBOOT", [], "node", "N018", "operador")
    assert op.destructive is True


async def test_create_rejects_unknown_command(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    with pytest.raises(NexusCommandError):
        await service.create(GW, "NOSUCHCOMMAND", [], "broadcast", None, "operador")


async def test_create_rejects_device_targeting(session_factory):
    """-device deshabilitado (ADR 0027 §0.2): ni siquiera existe como target_kind válido."""
    service = NexusOperationService(session_factory, FakeQueue())
    with pytest.raises(NexusTargetError):
        await service.create(GW, "STATS", [], "device", "!e53626b0", "operador")


async def test_create_node_target_requires_value(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    with pytest.raises(NexusTargetError):
        await service.create(GW, "STATS", [], "node", None, "operador")


async def test_created_operation_never_marks_or_sends(session_factory):
    """Crear NO despacha por sí solo — hace falta un tick del scheduler."""
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    await service.create(GW, "STATS", [], "broadcast", None, "operador")
    assert queue.sent == []


# ── Despacho (espaciado real de pacing.py) ────────────────────────────────


async def test_dispatch_sends_command_text_envelope(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "STATS", [], "broadcast", None, "operador")

    await service._dispatch(T0)

    assert len(queue.sent) == 1
    gateway_id, envelope = queue.sent[0]
    assert gateway_id == GW
    assert envelope["command_type"] == "command.send_text"
    assert envelope["payload"]["text"] == "/nexus STATS"
    assert envelope["issued_by"] == "operador"

    [refreshed] = await service.list_operations(GW)
    assert refreshed.id == op.id
    assert refreshed.status == "sent"
    # SQLite devuelve datetime naive (convención ya documentada del proyecto).
    assert refreshed.sent_at.replace(tzinfo=None) == T0.replace(tzinfo=None)


async def test_dispatch_respects_broadcast_cooldown(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    await service.create(GW, "STATS", [], "broadcast", None, "operador")
    await service._dispatch(T0)
    await service.create(GW, "INFO", [], "broadcast", None, "operador")

    await service._dispatch(at(2))  # dentro del cooldown de difusión
    assert len(queue.sent) == 1  # el segundo aún no

    await service._dispatch(at(10))  # cooldown + espaciado ya pasados
    assert len(queue.sent) == 2


async def test_dispatch_directed_to_different_targets_never_wait_on_each_other(session_factory):
    """Manual v2.8.006 (§1): -node se salta el cooldown de difusión — a
    destinos distintos, dos envíos dirigidos no se bloquean entre sí en
    absoluto (a diferencia de dos difusiones seguidas, que sí comparten la
    espera de 10s por destino — ver pacing.py::
    test_directed_sends_bypass_channel_cooldown, aquí solo se comprueba que
    el servicio conecta con ese comportamiento del núcleo puro, no se
    reimplementa)."""
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    await service.create(GW, "STATS", [], "node", "N018", "operador")
    await service._dispatch(T0)
    await service.create(GW, "INFO", [], "node", "OTR1", "operador")

    await service._dispatch(at(1))
    assert len(queue.sent) == 2  # destino distinto: sin espera alguna


async def test_dispatch_per_target_spacing(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    await service.create(GW, "STATS", [], "node", "N018", "operador")
    await service._dispatch(T0)
    await service.create(GW, "INFO", [], "node", "N018", "operador")

    await service._dispatch(at(5))  # mismo destino, aún dentro de los 10s
    assert len(queue.sent) == 1

    await service._dispatch(at(11))
    assert len(queue.sent) == 2


async def test_dispatch_two_gateways_are_independent(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    await service.create(GW, "STATS", [], "broadcast", None, "operador")
    await service.create("gw-otra", "STATS", [], "broadcast", None, "operador")
    await service._dispatch(T0)
    assert {g for g, _ in queue.sent} == {GW, "gw-otra"}


# ── Correlación de respuestas ──────────────────────────────────────────────


async def test_confirmed_when_response_matches(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "node", "N018", "operador")
    await service._dispatch(T0)

    await service.handle_event(message_event("!aaaaaaaa", "JT VERSION: 2.8.005.x", GW), now=at(1))

    [confirmed] = await service.list_operations(GW, status="confirmed")
    assert confirmed.id == op.id
    assert confirmed.response_kind == "structured"
    assert confirmed.response_data == {"version": "2.8.005.x"}
    assert confirmed.response_text == "JT VERSION: 2.8.005.x"


async def test_response_from_other_gateway_is_ignored(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "node", "N018", "operador")
    await service._dispatch(T0)

    await service.handle_event(message_event("!aaaaaaaa", "JT VERSION: 2.8.005.x", "gw-otra"), now=at(1))

    [still_sent] = await service.list_operations(GW)
    assert still_sent.id == op.id
    assert still_sent.status == "sent"


async def test_own_command_echo_is_not_a_response(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    await service.create(GW, "VERSION", [], "broadcast", None, "operador")
    await service._dispatch(T0)

    await service.handle_event(message_event("!af000001", "/nexus VERSION", GW), now=at(1))

    [op] = await service.list_operations(GW)
    assert op.status == "sent"


async def test_unrelated_traffic_before_any_dispatch_is_ignored(session_factory):
    """Sin ninguna operación enviada aún en esa pasarela, no hay ni siquiera
    estado en memoria que reensamble — coste cero en el caso común."""
    service = NexusOperationService(session_factory, FakeQueue())
    await service.handle_event(message_event("!aaaaaaaa", "hola", GW), now=at(1))  # no debe reventar
    assert await service.list_operations(GW) == []


async def test_paginated_response_confirms_after_silence(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "STATS", [], "node", "N018", "operador")
    await service._dispatch(T0)

    await service.handle_event(message_event("!aaaaaaaa", "P1: JT STATS:\nTX:1", GW), now=at(1))
    await service.handle_event(message_event("!aaaaaaaa", "P2:  RX:2", GW), now=at(2))
    [still_sent] = await service.list_operations(GW)
    assert still_sent.status == "sent"  # aún no ha pasado el silencio

    await service._flush_pending_assemblies(at(10))  # > quiet (8s) de ResponseAssembler
    [confirmed] = await service.list_operations(GW, status="confirmed")
    assert confirmed.id == op.id
    assert confirmed.response_text == "JT STATS:\nTX:1 RX:2"


# ── Vigilante de sin-respuesta ──────────────────────────────────────────────


async def test_no_response_after_window_expires(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "STATS", [], "broadcast", None, "operador")
    await service._dispatch(T0)

    await service._expire_stuck(at(DEFAULT_RESPONSE_WINDOW_SECONDS - 1))
    [still_sent] = await service.list_operations(GW)
    assert still_sent.status == "sent"

    await service._expire_stuck(at(DEFAULT_RESPONSE_WINDOW_SECONDS + 1))
    [expired] = await service.list_operations(GW, status="no_response")
    assert expired.id == op.id


async def test_no_response_window_extends_by_busy_seconds(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "REBOOT", [], "node", "N018", "operador")  # busy_seconds=20
    await service._dispatch(T0)

    await service._expire_stuck(at(DEFAULT_RESPONSE_WINDOW_SECONDS + 5))  # dentro del margen ampliado
    [still_sent] = await service.list_operations(GW)
    assert still_sent.id == op.id
    assert still_sent.status == "sent"

    await service._expire_stuck(at(DEFAULT_RESPONSE_WINDOW_SECONDS + 21))
    [expired] = await service.list_operations(GW, status="no_response")
    assert expired.id == op.id


async def test_late_response_after_no_response_is_not_reopened(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "node", "N018", "operador")
    await service._dispatch(T0)
    await service._expire_stuck(at(DEFAULT_RESPONSE_WINDOW_SECONDS + 1))

    await service.handle_event(
        message_event("!aaaaaaaa", "JT VERSION: 2.8.005.x", GW),
        now=at(DEFAULT_RESPONSE_WINDOW_SECONDS + 2),
    )

    [op_after] = await service.list_operations(GW)
    assert op_after.id == op.id
    assert op_after.status == "no_response"  # nunca se reabre


# ── Difusión/grupo: varias respuestas (ADR 0027 §11) ────────────────────────


async def test_broadcast_collects_multiple_responses(session_factory):
    """Pedido explícito del usuario: un comando por difusión debe dejar ver
    a CADA nodo que responda por separado, no un único estado agregado."""
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "broadcast", None, "operador")
    await service._dispatch(T0)

    await service.handle_event(message_event("!aaaaaaaa", "JT VERSION: 2.8.005.a", GW), now=at(1))
    await service.handle_event(message_event("!bbbbbbbb", "JT VERSION: 2.7.268.b", GW), now=at(3))

    # La operación sigue "sent" (escuchando) — no se cierra en la primera respuesta.
    [still_sent] = await service.list_operations(GW)
    assert still_sent.id == op.id
    assert still_sent.status == "sent"
    assert still_sent.response_text is None  # el campo único no se usa para difusión

    responses = await service.list_responses(op.id)  # type: ignore[arg-type]
    assert {r.from_node_id for r in responses} == {"!aaaaaaaa", "!bbbbbbbb"}
    by_node = {r.from_node_id: r for r in responses}
    assert by_node["!aaaaaaaa"].response_data == {"version": "2.8.005.a"}
    assert by_node["!bbbbbbbb"].response_data == {"version": "2.7.268.b"}


async def test_broadcast_confirmed_after_window_if_any_response(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "broadcast", None, "operador")
    await service._dispatch(T0)
    await service.handle_event(message_event("!aaaaaaaa", "JT VERSION: 2.8.005.a", GW), now=at(1))

    await service._expire_stuck(at(DEFAULT_RESPONSE_WINDOW_SECONDS + 1))

    [confirmed] = await service.list_operations(GW, status="confirmed")
    assert confirmed.id == op.id


async def test_group_target_also_collects_multiple_responses(session_factory):
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "group", "Perimetro", "operador")
    await service._dispatch(T0)

    await service.handle_event(message_event("!aaaaaaaa", "JT VERSION: 2.8.005.a", GW), now=at(1))
    await service.handle_event(message_event("!bbbbbbbb", "JT VERSION: 2.7.268.b", GW), now=at(2))

    [still_sent] = await service.list_operations(GW)
    assert still_sent.id == op.id
    assert still_sent.status == "sent"
    responses = await service.list_responses(op.id)  # type: ignore[arg-type]
    assert len(responses) == 2


async def test_node_target_never_writes_to_responses_table(session_factory):
    """Destino dirigido (node/mac/local): comportamiento intacto (terminal
    en la primera respuesta, campo único), sin tocar la tabla nueva."""
    queue = FakeQueue()
    service = NexusOperationService(session_factory, queue)
    op = await service.create(GW, "VERSION", [], "node", "N018", "operador")
    await service._dispatch(T0)
    await service.handle_event(message_event("!aaaaaaaa", "JT VERSION: 2.8.005.a", GW), now=at(1))

    [confirmed] = await service.list_operations(GW, status="confirmed")
    assert confirmed.id == op.id
    assert confirmed.response_text == "JT VERSION: 2.8.005.a"
    assert await service.list_responses(op.id) == []  # type: ignore[arg-type]
