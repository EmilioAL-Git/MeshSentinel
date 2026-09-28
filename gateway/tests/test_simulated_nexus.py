"""Simulación de respuesta JenTastic-Nexus (ADR 0027): solo lo mínimo para
probar el flujo de detección sin hardware — responde a `/nexus ... INFO`
desde nodos distintos del local, con el formato real observado en campo."""

from gateway.config import Settings
from gateway.transports.simulated import SimulatedTransport


def make_transport(seed: int = 42, node_count: int = 5) -> tuple[SimulatedTransport, list[dict]]:
    emitted: list[dict] = []

    async def emit(event_type: str, payload: dict) -> None:
        emitted.append({"event_type": event_type, "payload": payload})

    settings = Settings(_env_file=None, transport="simulated", sim_node_count=node_count, sim_seed=seed)
    return SimulatedTransport(emit, settings), emitted


async def test_info_broadcast_gets_simulated_jt_replies():
    t, emitted = make_transport()
    await t.send_command({"command_type": "command.send_text", "payload": {"text": "/nexus INFO"}})
    received = [e for e in emitted if e["event_type"] == "message.received"]
    assert len(received) == 2  # self._nodes[1:3]
    for e in received:
        text = e["payload"]["text"]
        assert text.startswith("JT INFO:")
        assert e["payload"]["from_node_id"] in (t._nodes[1].node_id, t._nodes[2].node_id)


async def test_local_node_never_replies_to_itself():
    t, emitted = make_transport()
    await t.send_command({"command_type": "command.send_text", "payload": {"text": "/nexus INFO"}})
    received = [e for e in emitted if e["event_type"] == "message.received"]
    assert all(e["payload"]["from_node_id"] != t._nodes[0].node_id for e in received)


async def test_only_info_command_triggers_a_reply():
    t, emitted = make_transport()
    await t.send_command({"command_type": "command.send_text", "payload": {"text": "/nexus STATS"}})
    assert [e for e in emitted if e["event_type"] == "message.received"] == []


async def test_other_command_types_are_untouched():
    t, emitted = make_transport()
    await t.send_command({"command_type": "command.request_position", "payload": {}})
    assert emitted == []


async def test_reply_matches_the_real_field_format():
    """El texto simulado debe ser real de verdad (formato de la captura de
    campo, ADR 0027 §0.0): cabecera "JT INFO:", id+short entre corchetes,
    Ver:/Role:/MAC: etiquetados. No se importa el parser del backend aquí a
    propósito (ADR 0001: gateway y backend nunca comparten código Python,
    solo el contrato) — se valida el formato con una regex propia, mínima."""
    import re

    info_re = re.compile(
        r"^JT INFO:\n(?P<node_id>![0-9a-f]{8}) \[(?P<short>[^\]]+)\]\n"
        r"Ver: \S+\nRole: \S+\nMAC: [0-9a-f:]+$"
    )
    t, emitted = make_transport()
    await t.send_command({"command_type": "command.send_text", "payload": {"text": "/nexus INFO"}})
    received = [e for e in emitted if e["event_type"] == "message.received"]
    for e in received:
        match = info_re.match(e["payload"]["text"])
        assert match, e["payload"]["text"]
        assert match.group("node_id") == e["payload"]["from_node_id"]
