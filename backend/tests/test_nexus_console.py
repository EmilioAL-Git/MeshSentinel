"""Consola Nexus: interpretación de respuestas, listas conocidas de favoritos/
ignorados alimentadas por las confirmaciones, y la vista de conversación."""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from noc.adapters.persistence.chat_repositories import SqlChatRepository
from noc.adapters.persistence.models import GatewayModel, NodeModel
from noc.application.nexus.interpret import ERROR, INFO, OK, interpret
from noc.application.nexus_conversation import NexusConversationService
from noc.application.nexus_operations import NexusOperationService
from noc.domain.chat.entities import ChatMessage

GW = "gw-test"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


class FakeQueue:
    async def enqueue(self, gateway_id: str, envelope: dict) -> None:
        pass


def msg_event(from_node_id: str, text: str) -> dict:
    return {
        "schema_version": 1, "event_type": "message.received", "event_id": str(uuid.uuid4()),
        "gateway_id": GW, "timestamp": T0.isoformat(),
        "payload": {"from_node_id": from_node_id, "text": text},
    }


# ── Intérprete puro ─────────────────────────────────────────────────────


def test_ignore_is_interpreted_with_subject_label():
    i = interpret("IGNORE", ("!1234abcd",), "JT: Nodo ignorado", subject_label="Foo (!1234abcd)")
    assert i is not None and i.outcome == OK
    assert i.summary == "Nodo Foo (!1234abcd) ignorado correctamente"
    assert (i.flag_type, i.flag_present, i.subject_node_id) == ("ignored", True, "!1234abcd")


def test_fav_updated_node_real_format():
    i = interpret("FAV", ("!1234abcd",), "JT: Updated node 1234abcd (N001)")
    # el formato real lleva "!" — sin él no encaja con el parser, cae al patrón tolerante
    assert i is not None and i.outcome == OK and i.flag_type == "favorite" and i.flag_present is True
    j = interpret("UNFAV", ("!1234abcd",), "🟢 JT: Updated node !1234abcd (N001)")
    assert j is not None and j.flag_present is False and j.subject_short_name == "N001"
    assert "quitado de favoritos" in j.summary


def test_unrecognised_ignore_reply_is_not_interpreted():
    assert interpret("IGNORE", ("!1234abcd",), "JT: algo raro") is None
    assert interpret("IGNORE", ("!1234abcd",), "hola que tal") is None


def test_error_reply_and_unknown_command():
    e = interpret("IGNORE", ("!1234abcd",), "JT: Invalid node")
    assert e is not None and e.outcome == ERROR and e.flag_type is None
    u = interpret("SETROLE", (), "JT: Unknown command 'SETROLE'")
    assert u is not None and u.outcome == ERROR


def test_list_summaries_only_when_complete():
    text = "JT Favorites:\n!af000004:N002 !af000005:N003"
    assert interpret("FAVS", (), "P1: " + text, complete=False) is None
    i = interpret("FAVS", (), text)
    assert i is not None and i.outcome == INFO and i.summary == "2 favoritos"


# ── Listas conocidas ────────────────────────────────────────────────────


async def test_confirmations_feed_known_lists_per_responder(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    conv = NexusConversationService(session_factory)
    op = await service.create(GW, "IGNORE", ["!1234abcd"], "broadcast", None, "operador")
    await service._dispatch(T0)
    await service.handle_event(msg_event("!aaaaaaaa", "JT: Nodo ignorado"), now=at(1))
    await service.handle_event(msg_event("!bbbbbbbb", "JT: Nodo ignorado"), now=at(2))
    assert op.id

    for holder in ("!aaaaaaaa", "!bbbbbbbb"):
        flags = await conv.known_flags(holder)
        assert [(f.flag_type, f.subject_node_id) for f in flags] == [("ignored", "!1234abcd")]

    # UNIGNORE lo quita solo del que confirma
    await service.create(GW, "UNIGNORE", ["!1234abcd"], "node", "AAA", "operador")
    await service._dispatch(at(30))
    await service.handle_event(msg_event("!aaaaaaaa", "JT: Nodo ignorado"), now=at(31))
    assert await conv.known_flags("!aaaaaaaa") == []
    assert len(await conv.known_flags("!bbbbbbbb")) == 1


async def test_favs_read_replaces_list(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    conv = NexusConversationService(session_factory)
    await service.create(GW, "FAV", ["!1234abcd"], "node", "AAA", "operador")
    await service._dispatch(T0)
    await service.handle_event(msg_event("!aaaaaaaa", "JT: Updated node !1234abcd (X1)"), now=at(1))
    assert len(await conv.known_flags("!aaaaaaaa")) == 1

    await service.create(GW, "FAVS", [], "node", "AAA", "operador")
    await service._dispatch(at(40))
    await service.handle_event(msg_event("!aaaaaaaa", "JT Favorites:\n!af000004:N002"), now=at(41))
    await service._flush_pending_assemblies(at(60))
    flags = await conv.known_flags("!aaaaaaaa")
    assert [f.subject_node_id for f in flags] == ["!af000004"]


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
async def test_paginated_favs_fills_known_list_in_any_arrival_order(session_factory, order):
    """Por radio el orden NO está garantizado: P1, P2 y el aviso «Paging … to
    mesh…» pueden llegar en cualquiera de las 6 permutaciones (observadas
    reales: P1-P2-aviso y P1-aviso-P2). El resultado debe ser siempre la lista
    completa en la tabla de favoritos conocidos."""
    parts = [
        "P1: JT Favorites:\n!af000004:N002 !af000005:N0",
        "P2: 03",
        "🟢 JT: Paging favorites to mesh...",
    ]
    service = NexusOperationService(session_factory, FakeQueue())
    conv = NexusConversationService(session_factory)
    await service.create(GW, "FAVS", [], "node", "AAA", "operador")
    await service._dispatch(T0)
    for step, idx in enumerate(order, start=1):
        await service.handle_event(msg_event("!aaaaaaaa", parts[idx]), now=at(step))
    await service._flush_pending_assemblies(at(30))
    flags = await conv.known_flags("!aaaaaaaa")
    assert sorted(f.subject_node_id for f in flags) == ["!af000004", "!af000005"]


# ── Conversación ────────────────────────────────────────────────────────


async def test_conversation_annotates_replies_with_interpretation(session_factory):
    now = datetime.now(timezone.utc)
    async with session_factory() as session, session.begin():
        session.add(GatewayModel(
            id=GW, status="connected", transport="usb", updated_at=now,
            channels=[{"index": 0, "name": "LongFast"}, {"index": 7, "name": "Nexus"}],
        ))
        for nid, sn in (("!aaaaaaaa", "AAA"), ("!1234abcd", "TGT")):
            session.add(NodeModel(id=nid, short_name=sn, long_name=f"Nodo {sn}", first_seen_at=now, last_seen_at=now))
    service = NexusOperationService(session_factory, FakeQueue())
    op = await service.create(GW, "IGNORE", ["!1234abcd"], "broadcast", None, "operador")
    await service._dispatch(now)
    async with session_factory() as session, session.begin():
        repo = SqlChatRepository(session)
        await repo.add(ChatMessage(from_node_id="!aaaaaaaa", text="JT: Nodo ignorado", gateway_id=GW,
                                   channel_index=7, received_at=now + timedelta(seconds=2)))
        await repo.add(ChatMessage(from_node_id="!aaaaaaaa", text="ruido", gateway_id=GW,
                                   channel_index=0, received_at=now + timedelta(seconds=3)))

    conv = await NexusConversationService(session_factory).conversation(None)
    assert [m.message.text for m in conv.messages] == ["JT: Nodo ignorado"]  # solo el canal Nexus
    [m] = conv.messages
    assert m.context_op_id == op.id
    assert m.interpretation is not None
    assert m.interpretation.summary == "Nodo Nodo TGT (!1234abcd) ignorado correctamente"
    assert [o.id for o in conv.operations] == [op.id]


# ── Formatos reales de campo (2026-10-01, T1000 2.8.005 desde el X1) ────


def test_ignore_real_field_formats():
    ok = interpret("IGNORE", ("!e7ef4fb4",), "🟢 JT: Updated node !e7ef4fb4 (CALP)")
    assert ok is not None and ok.outcome == OK and ok.flag_type == "ignored" and ok.flag_present is True
    assert ok.subject_short_name == "CALP"
    un = interpret("UNIGNORE", ("!e7ef4fb4",), "🟢 JT: Updated node !e7ef4fb4 (CALP)")
    assert un is not None and un.flag_present is False
    nf = interpret("IGNORE", ("!a35bbe04",), "🟢 JT: Node '!a35bbe04' not found")
    assert nf is not None and nf.outcome == ERROR and nf.flag_type is None


def test_forced_variants_never_change_known_lists():
    # FIGNORE confirmó «Updated node» sin ignorar nada (verificado con IGNORED).
    for cmd, text in (
        ("FIGNORE", "🟢 JT: Updated node !e7ef4fb4 (CALP)"),
        ("FUNIGNORE", "🟢 JT: Forced node !e7ef4fb4 (CALP)"),
        ("FFAV", "🟢 JT: Updated node !e7ef4fb4 (CALP)"),
        ("FUNFAV", "🟢 JT: Forced node !e7ef4fb4 (CALP)"),
    ):
        i = interpret(cmd, ("!e7ef4fb4",), text)
        assert i is not None and i.outcome == INFO and i.flag_type is None, cmd
    e = interpret("FIGNORE", ("!0badc0de",), "🟢 JT: Node '0badc0de' not found")
    assert e is not None and e.outcome == ERROR


async def test_fignore_confirmation_does_not_feed_known_list(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    conv = NexusConversationService(session_factory)
    await service.create(GW, "FIGNORE", ["!1234abcd"], "broadcast", None, "operador")
    await service._dispatch(T0)
    await service.handle_event(msg_event("!aaaaaaaa", "JT: Updated node !1234abcd (TGT)"), now=at(1))
    assert await conv.known_flags("!aaaaaaaa") == []


# ── NIGN (ignorados persistentes), formatos reales 2026-10-01 ───────────


def test_nign_real_field_formats():
    add = interpret("NIGN", ("ADD", "!e7ef4fb4"), "🟢 JT: !e7ef4fb4 ADDED to ignores", subject_label="CALP (!e7ef4fb4)")
    assert add is not None and add.outcome == OK
    assert (add.flag_type, add.flag_present, add.subject_node_id) == ("nign", True, "!e7ef4fb4")
    assert "ignorados persistentes" in add.summary
    rem = interpret("NIGN", ("REM", "!e7ef4fb4"), "🟢 JT: !e7ef4fb4 REMOVED")
    assert rem is not None and rem.flag_present is False and rem.flag_type == "nign"
    lst = interpret("NIGN", ("LIST",), "🟢 JT JT Ignores:\n[0] !e7ef4fb4 (CALP)\n")
    assert lst is not None and lst.outcome == INFO and lst.summary == "1 ignorados persistentes"
    empty = interpret("NIGN", ("LIST",), "JT JT Ignores:\nList empty.\n")
    assert empty is not None and empty.data == {"entries": []}


async def test_nign_is_a_separate_list_from_ignore(session_factory):
    service = NexusOperationService(session_factory, FakeQueue())
    conv = NexusConversationService(session_factory)
    await service.create(GW, "NIGN", ["ADD", "!1234abcd"], "node", "AAA", "operador")
    await service._dispatch(T0)
    await service.handle_event(msg_event("!aaaaaaaa", "JT: !1234abcd ADDED to ignores"), now=at(1))
    assert [(f.flag_type, f.subject_node_id) for f in await conv.known_flags("!aaaaaaaa")] == [("nign", "!1234abcd")]

    # una lectura de IGNORED (RAM) no toca la lista persistente
    await service.create(GW, "IGNORED", [], "node", "AAA", "operador")
    await service._dispatch(at(40))
    await service.handle_event(msg_event("!aaaaaaaa", "JT Ignored:\n"), now=at(41))
    await service._flush_pending_assemblies(at(60))
    assert [f.flag_type for f in await conv.known_flags("!aaaaaaaa")] == ["nign"]

    await service.create(GW, "NIGN", ["LIST"], "node", "AAA", "operador")
    await service._dispatch(at(80))
    await service.handle_event(msg_event("!aaaaaaaa", "JT JT Ignores:\nList empty.\n"), now=at(81))
    await service._flush_pending_assemblies(at(100))
    assert await conv.known_flags("!aaaaaaaa") == []


def test_nign_idempotent_replies_keep_the_list_consistent():
    again = interpret("NIGN", ("ADD", "!e7ef4fb4"), "🟢 JT: !e7ef4fb4 already ignored")
    assert again is not None and again.outcome == OK and again.flag_present is True
    assert "ya estaba" in again.summary
    gone = interpret("NIGN", ("REM", "!e7ef4fb4"), "🟢 JT: !e7ef4fb4 not in list")
    assert gone is not None and gone.outcome == OK and gone.flag_present is False
    assert "no estaba" in gone.summary


def test_uptime_and_generic_interpretation():
    i = interpret("UPTIME", (), "🟢 JT UPTIME: 3d 0h 53m 14s", complete=False)
    assert i is not None and i.outcome == INFO
    assert i.summary == "UPTIME — uptime: 3d 0h 53m 14s · seconds: 262394"
    v = interpret("VERSION", (), "🔒 JT VERSION: 2.8.005.b42309e", complete=False)
    assert v is not None and "2.8.005.b42309e" in v.summary
    # una página suelta de una respuesta paginada no se resume
    assert interpret("STATS", (), "P1: JT STATS:\nTX:1", complete=False) is None


# --- Respuestas paginadas: una respuesta = una burbuja -----------------------


def _chat(text, sec, node="!215baaee", gw="gw-02"):
    from datetime import datetime, timedelta, timezone

    from noc.domain.chat.entities import ChatMessage

    base = datetime(2026, 10, 1, 16, 33, 0, tzinfo=timezone.utc)
    return ChatMessage(from_node_id=node, text=text, gateway_id=gw, received_at=base + timedelta(seconds=sec))


def test_merge_paginated_joins_pages_and_absorbs_trailer():
    from noc.application.nexus_conversation import merge_paginated

    merged = merge_paginated([
        _chat("P1: JT Favorites:\n!c9df912c:AB86 !7c5ac2c4:EA", 0),
        _chat("P2: L1 !0c871e4e:MIKJ", 2.5),
        _chat("🟢 JT: Paging favorites to mesh...", 4.8),
    ])
    assert len(merged) == 1
    msg, parts = merged[0]
    assert parts == 3
    # Sin separador: el firmware trocea a ciegas (aquí a mitad de «EAL1»).
    assert msg.text == "JT Favorites:\n!c9df912c:AB86 !7c5ac2c4:EAL1 !0c871e4e:MIKJ"


def test_merge_paginated_keeps_other_senders_and_new_responses_apart():
    from noc.application.nexus_conversation import merge_paginated

    merged = merge_paginated([
        _chat("P1: JT Ignored:\n", 0),
        _chat("🟢 JT UPTIME: 3d 0h", 1, node="!aaaaaaaa"),  # otro nodo en medio
        _chat("🟢 JT: Paging ignored to mesh...", 3),
        _chat("P1: JT Favorites:\n", 40),  # >8 s de silencio: respuesta nueva
        _chat("🟢 JT: Paging x to mesh...", 90),  # sin páginas abiertas: mensaje normal
    ])
    assert [(m.text[:14], parts) for m, parts in merged] == [
        ("JT Ignored:\n", 2),
        ("🟢 JT UPTIME: 3", 0),
        ("JT Favorites:\n", 1),
        ("🟢 JT: Paging x", 0),
    ]
