"""Módulo nexus_control (ADR 0027): núcleo puro, sin transporte ni BD.

Cubre direccionamiento (§1), catálogo cerrado, constructor (ZH truncado,
bloqueo en difusión, destructivos, SAVE), espaciado, reensamblado con
deduplicación, correlación y el registro de parsers (sin formatos aún).
"""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from noc.application.nexus import catalog
from noc.application.nexus.addressing import (
    Broadcast,
    Device,
    Group,
    Local,
    Mac,
    NexusAddressError,
    ShortName,
    is_command_text,
    normalize_node_id,
    render_prefix,
    zero_hop_suffix,
)
from noc.application.nexus.builder import MAX_TEXT_CHARS, NexusCommandError, build_command
from noc.application.nexus.correlation import ResponseCorrelator
from noc.application.nexus.pacing import CommandPacer
from noc.application.nexus.parsers import PARSERS, PENDING_FORMATS, parse_response
from noc.application.nexus.reassembly import IncomingText, ResponseAssembler

T0 = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
NODE = "!e53626b0"
OTHER = "!21de52ee"
# Direccionamiento real del módulo: solo -node <shortname> (Device
# deshabilitado en el builder, ver test_device_addressing_disabled_in_builder).
SHORT = ShortName("N018")
SHORT_OTHER = ShortName("OTR1")


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


# --- Direccionamiento ---------------------------------------------------------


@pytest.mark.parametrize("raw", ["!e53626b0", "0xe53626b0", "xe53626b0", "e53626b0", "!E53626B0"])
def test_hex_id_parser_is_tolerant(raw: str) -> None:
    assert normalize_node_id(raw) == NODE


@pytest.mark.parametrize("raw", ["", "!e53626", "!e53626b0ff", "!zz3626b0"])
def test_hex_id_parser_rejects_garbage(raw: str) -> None:
    with pytest.raises(NexusAddressError):
        normalize_node_id(raw)


def test_zero_hop_uses_last_two_hex_chars() -> None:
    assert zero_hop_suffix("0xE53626B0") == "b0"


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (Broadcast(), "/nexus STATS"),
        (Local(), "/nexus-local STATS"),
        (ShortName("N018"), "/nexus-node N018 STATS"),
        (Mac("1ABCDE"), "/nexus-mac 1abcde STATS"),
        (Group("centro"), "/nexus-group centro STATS"),
    ],
)
def test_addressing_suffixes(target, expected: str) -> None:
    assert build_command("STATS", target=target).text == expected


def test_device_prefix_renders_as_a_protocol_primitive() -> None:
    assert render_prefix(Device("0x21de52ee")) == "/nexus-device !21de52ee"


def test_device_addressing_allowed_in_builder() -> None:
    # -device reincorporado como opción consciente (ADR 0027 §13,
    # 2026-09-29): el usuario confirmó conocer la causa del fallo de campo
    # original (node_id regenerado tras reflashear) y quiere poder elegirlo
    # de todos modos — build_command ya no lo rechaza; la preselección
    # segura por defecto vive en el ajuste `addressing_mode`, no aquí.
    cmd = build_command("STATS", target=Device(NODE))
    assert cmd.text == f"/nexus-device {NODE} STATS"


def test_invalid_mac_and_names() -> None:
    with pytest.raises(NexusAddressError):
        Mac("1ab")
    with pytest.raises(NexusAddressError):
        build_command("STATS", target=ShortName("AB MO"))


@pytest.mark.parametrize(
    "text", ["/nexus STATS", "/JT INFO", "/jent-device !21de52ee CH", "/jentastic-local", "/nexus"]
)
def test_command_text_recognised(text: str) -> None:
    assert is_command_text(text)


@pytest.mark.parametrize("text", ["P1: Uptime 3h", "nexus STATS", "/nexusSTATS", "hola"])
def test_non_command_text(text: str) -> None:
    assert not is_command_text(text)


# --- Catálogo -----------------------------------------------------------------


def test_aliases_resolve_to_canonical() -> None:
    assert build_command("sec").text == "/nexus SECURITY"
    assert build_command("MEM").spec.name == "RAM"
    assert build_command("fws").spec.name == "FIREWALLSTATS"


def test_excluded_and_unknown_commands_rejected() -> None:
    # FSIG y SETTINGS son comandos reales (manual v2.8.006); AIRTAG sigue
    # excluido (el propio manual: "NOT IMPLEMENTED"); BURNER/ROLEMASK
    # confirmados ausentes de la build pública; "OTA" SÍ existe (alias real
    # de WIFIOTA) — "NOSUCHCOMMAND" es el caso realmente inexistente.
    for name in ("AIRTAG", "BURNER", "ROLEMASK", "NOSUCHCOMMAND"):
        with pytest.raises(NexusCommandError):
            build_command(name)


def test_rl_alias_resolved_by_manual() -> None:
    # El manual v2.8.006 (verificado contra el código fuente) resuelve la
    # ambigüedad: RL es de RATELIMIT; RSSILOG usa PL como alias.
    assert catalog.resolve("RL").name == "RATELIMIT"
    assert catalog.resolve("PL").name == "RSSILOG"
    assert catalog.resolve("RSSILOG") is not None
    assert catalog.resolve("RATELIMIT") is not None


def test_catalog_has_no_alias_collisions() -> None:
    names = set(catalog.COMMANDS)
    assert not names & set(catalog.ALIASES)
    all_aliases = [a for s in catalog.COMMANDS.values() for a in s.aliases]
    assert len(all_aliases) == len(set(all_aliases))


# --- Constructor --------------------------------------------------------------


def test_zh_add_del_truncate_id_automatically() -> None:
    assert build_command("ZH", ["add", "!e53626b0"]).text == "/nexus ZH ADD b0"
    assert build_command("ZH", ["DEL", "0xE53626B0"]).text == "/nexus ZH DEL b0"
    # Otros subverbos no se tocan
    assert build_command("ZH", ["ON"]).text == "/nexus ZH ON"


@pytest.mark.parametrize("name", ["NAME", "OWNER", "REVERT"])
@pytest.mark.parametrize("target", [Broadcast(), Group("centro")])
def test_identity_commands_forbidden_on_multi_node(name: str, target) -> None:
    with pytest.raises(NexusCommandError):
        build_command(name, ["X"], target=target)


def test_identity_command_allowed_on_single_device() -> None:
    cmd = build_command("OWNER", ["N018", "AB-MOLATOWER"], target=SHORT)
    assert cmd.text == "/nexus-node N018 OWNER N018 AB-MOLATOWER"
    assert cmd.destructive


@pytest.mark.parametrize(
    ("name", "args"),
    [("REVERT", ()), ("NAME", ("x",)), ("OWNER", ("a", "b")), ("DELNODE", (OTHER,)),
     ("ZH", ("CLEAR",)), ("RDROP", ("CLEAR",))],
)
def test_destructive_commands_flagged(name: str, args) -> None:
    assert build_command(name, args, target=SHORT).destructive


@pytest.mark.parametrize(("name", "args"), [("ZH", ("LIST",)), ("RDROP", ("*ab",)), ("STATS", ())])
def test_non_destructive(name: str, args) -> None:
    assert not build_command(name, args, target=SHORT).destructive


def test_requires_save_semantics() -> None:
    assert build_command("SETCONFIG", ["NI", "43200"]).requires_save
    assert build_command("SECURITY", ["ALLOW_DM", "on"]).requires_save  # §2.3 explícito
    assert not build_command("SECURITY").requires_save  # overview, solo lectura
    assert not build_command("ZH", ["LIST"]).requires_save
    assert not build_command("RATELIMIT", ["POS", "10"]).requires_save  # auto-persistente
    assert not build_command("REBOOT", target=SHORT).requires_save
    assert not build_command("STATS").requires_save


def test_busy_seconds_from_document() -> None:
    assert build_command("FREQSCAN", ["868", "250"], target=SHORT).busy_seconds == 15
    assert build_command("REBOOT", target=SHORT).busy_seconds == 20
    assert build_command("SETLORA", ["10", "800", "5", "2482"], target=SHORT).busy_seconds == 5


@pytest.mark.parametrize("bad", ["a;REVERT", "", "a\nb"])
def test_args_cannot_chain_commands(bad: str) -> None:
    with pytest.raises(NexusCommandError):
        build_command("ALIAS", ["SET", bad])


def test_text_length_limit() -> None:
    with pytest.raises(NexusCommandError):
        build_command("TEXT", ["x" * MAX_TEXT_CHARS])
    build_command("TEXT", ["x" * (MAX_TEXT_CHARS - len("/nexus TEXT "))])  # justo en el límite


@pytest.mark.parametrize(
    ("name", "args"),
    [("ZH", ("IMPORT", "QUJDREEEAA==")), ("SETLORA", ("10", "800", "5", "2482")),
     ("REBOOT", ()), ("TX", ("OFF",)), ("SETSYNCWORD", ("0x2C",))],
)
def test_new_destructive_commands_from_v2_8_006(name: str, args) -> None:
    assert build_command(name, args, target=SHORT).destructive


@pytest.mark.parametrize(
    ("name", "args"),
    [("ZH", ("EXPORT",)), ("TX", ("ON",)), ("SETSYNCWORD", ("0x2B",)),
     ("SETSYNCWORD", ("0X2b",)), ("SETSYNCWORD", ())],
)
def test_not_destructive_by_value(name: str, args) -> None:
    assert not build_command(name, args, target=SHORT).destructive


def test_fsig_no_longer_excluded() -> None:
    assert build_command("FSIG").text == "/nexus FSIG"


def test_prallow_is_alias_of_prwhitelist() -> None:
    # El manual v2.8.006: "PRWHITELIST / PRALLOW" es UNA fila, no dos
    # comandos — PRALLOW expande al nombre canónico PRWHITELIST.
    assert build_command("PRWHITELIST", ["ADD", "abcd1234"]).text == \
        "/nexus PRWHITELIST ADD abcd1234"
    assert build_command("PRALLOW", ["ADD", "abcd1234"]).text == \
        "/nexus PRWHITELIST ADD abcd1234"
    assert build_command("PRBLOCK", ["ADD", "0xC3"]).spec.name == "PRBLACKLIST"


def test_settings_is_distinct_from_config() -> None:
    settings = build_command("SETTINGS")
    config = build_command("CONFIG")
    assert settings.text == "/nexus SETTINGS"
    assert config.text == "/nexus CONFIG"
    assert not settings.mutates


def test_redirect_depth_limit() -> None:
    ok = build_command("R", ["CH", "centro", "STATS"], target=SHORT)
    assert ok.text == "/nexus-node N018 REDIRECT CH centro STATS"  # nombre canónico
    nested_ok = build_command(
        "REDIRECT", ["CH", "centro", "R", "DM", "!21de52ee", "STATS"], target=SHORT
    )
    assert nested_ok.spec.name == "REDIRECT"
    with pytest.raises(NexusCommandError):
        build_command(
            "R",
            ["CH", "a", "R", "DM", "b", "R", "CH", "c", "STATS"],
            target=SHORT,
        )


# --- Espaciado ----------------------------------------------------------------


def test_directed_sends_bypass_channel_cooldown() -> None:
    # Manual v2.8.006 (§1, verificado contra el código): -device/-node se
    # saltan el cooldown de difusión explícitamente ("Bypasses broadcast
    # cooldown"). Dos envíos dirigidos a nodos distintos no se bloquean
    # entre sí por el cooldown de canal (solo por el espaciado de 10 s si
    # fuera al MISMO destino).
    pacer = CommandPacer()
    a = build_command("STATS", target=SHORT)
    b = build_command("STATS", target=SHORT_OTHER)
    assert pacer.next_allowed_at(a, T0) == T0
    pacer.record_sent(a, T0)
    assert pacer.next_allowed_at(b, at(1)) == at(1)


def test_channel_cooldown_only_between_broadcasts() -> None:
    # Dos difusiones seguidas comparten la clave de destino "_ALL", así que
    # el espaciado de 10 s (regla 2, más estricto) domina el resultado sobre
    # el cooldown de canal de 5 s (regla 1) — este último solo se distingue
    # de la regla 2 cuando el cooldown fuera MAYOR (con channel_cooldown
    # configurado por encima de per_target_spacing).
    pacer = CommandPacer(channel_cooldown=timedelta(seconds=20))
    a = build_command("STATS")  # difusión
    b = build_command("INFO")  # difusión
    pacer.record_sent(a, T0)
    assert pacer.next_allowed_at(b, at(1)) == at(20)


def test_same_target_spaced_ten_seconds() -> None:
    pacer = CommandPacer()
    cmd = build_command("STATS", target=SHORT)
    pacer.record_sent(cmd, T0)
    assert pacer.next_allowed_at(cmd, at(6)) == at(10)


def test_busy_node_waits_longer_than_spacing() -> None:
    pacer = CommandPacer()
    pacer.record_sent(build_command("REBOOT", target=SHORT), T0)
    assert pacer.next_allowed_at(build_command("INFO", target=SHORT), at(1)) == at(20)
    # Otro nodo, dirigido: no espera nada (bypasea el cooldown y no está ocupado).
    assert pacer.next_allowed_at(build_command("INFO", target=SHORT_OTHER), at(1)) == at(1)


def test_broadcast_blocks_single_targets_and_vice_versa() -> None:
    pacer = CommandPacer()
    pacer.record_sent(build_command("STATS"), T0)
    assert pacer.next_allowed_at(build_command("INFO", target=SHORT), at(6)) == at(10)

    pacer = CommandPacer()
    pacer.record_sent(build_command("FREQSCAN", ["868", "250"], target=SHORT), T0)
    assert pacer.next_allowed_at(build_command("STATS"), at(6)) == at(15)


# --- Reensamblado y deduplicación ---------------------------------------------


def msg(text: str, seconds: float, node: str = NODE, packet_id: int | None = None) -> IncomingText:
    return IncomingText(node, text, at(seconds), packet_id)


def test_single_message_response_completes_immediately() -> None:
    [resp] = ResponseAssembler().feed(msg("Uptime: 3h", 0))
    assert resp.text == "Uptime: 3h"
    assert not resp.paginated


def test_pages_reassembled_after_quiet_period() -> None:
    asm = ResponseAssembler()
    assert asm.feed(msg("P1: linea uno", 0)) == []
    assert asm.feed(msg("P2: linea dos", 2)) == []
    assert asm.flush_expired(at(9)) == []  # 7 s de silencio: aún abierta
    [resp] = asm.flush_expired(at(10))
    assert resp.text == "linea unolinea dos"  # sin separador (captura real)
    assert resp.pages == (1, 2)
    assert resp.missing_pages == ()
    assert resp.first_at == at(0) and resp.last_at == at(2)


def test_out_of_order_and_missing_pages() -> None:
    asm = ResponseAssembler()
    asm.feed(msg("P3: c", 0))
    asm.feed(msg("P1: a", 1))
    [resp] = asm.flush_expired(at(20))
    assert resp.text == "ac"
    assert resp.missing_pages == (2,)


def test_new_p1_closes_previous_response() -> None:
    asm = ResponseAssembler()
    asm.feed(msg("P1: primera", 0))
    asm.feed(msg("P2: primera-b", 2))
    [done] = asm.feed(msg("P1: segunda", 12))
    assert done.text == "primeraprimera-b"
    [second] = asm.flush_expired(at(30))
    assert second.text == "segunda"


def test_interleaved_nodes_have_separate_buffers() -> None:
    asm = ResponseAssembler()
    asm.feed(msg("P1: a1", 0, NODE))
    asm.feed(msg("P1: b1", 0.5, OTHER))
    asm.feed(msg("P2: a2", 2, NODE))
    asm.feed(msg("P2: b2", 2.5, OTHER))
    result = {r.from_node_id: r.text for r in asm.flush_expired(at(20))}
    assert result == {NODE: "a1a2", OTHER: "b1b2"}


def test_duplicate_copy_dropped_by_text_and_packet_id() -> None:
    asm = ResponseAssembler()
    assert len(asm.feed(msg("OK", 0, packet_id=1))) == 1
    assert asm.feed(msg("OK", 0.3, packet_id=2)) == []  # copia al móvil local
    assert asm.feed(msg("OK", 0.4, packet_id=1)) == []  # mismo paquete, otra pasarela
    asm.feed(msg("P1: x", 1, packet_id=3))
    assert asm.feed(msg("P1: x", 1.2, packet_id=4)) == []  # página duplicada
    [resp] = asm.flush_expired(at(20))
    assert resp.text == "x"


def test_identical_response_later_is_not_a_duplicate() -> None:
    asm = ResponseAssembler()
    asm.feed(msg("OK", 0))
    assert len(asm.feed(msg("OK", 12))) == 1


def test_command_echo_is_not_a_response() -> None:
    assert ResponseAssembler().feed(msg("/nexus-device !e53626b0 STATS", 0)) == []


# --- Correlación --------------------------------------------------------------


def resp_from(node: str, seconds: float):
    return ResponseAssembler().feed(msg("OK", seconds, node))[0]


def test_device_command_only_matches_its_node() -> None:
    cor = ResponseCorrelator()
    cor.register("c1", Device(NODE), T0)
    assert cor.match(resp_from(OTHER, 2)) is None
    assert cor.match(resp_from(NODE, 2)) == "c1"


def test_broadcast_matches_any_responder_and_expires() -> None:
    cor = ResponseCorrelator()
    cor.register("c1", Broadcast(), T0)
    assert cor.match(resp_from(NODE, 3)) == "c1"
    assert cor.match(resp_from(OTHER, 4)) == "c1"
    assert cor.match(resp_from(NODE, 31)) is None


def test_specific_command_beats_broadcast_and_busy_extends_window() -> None:
    cor = ResponseCorrelator()
    cor.register("dev", Device(NODE), T0, busy_seconds=60)
    cor.register("all", Broadcast(), at(5))
    assert cor.match(resp_from(NODE, 6)) == "dev"
    assert cor.match(resp_from(OTHER, 6)) == "all"
    assert cor.match(resp_from(NODE, 80)) == "dev"  # 30 s + 60 s de NETSCAN


def test_local_target_matches_gateway_local_node() -> None:
    cor = ResponseCorrelator()
    cor.register("loc", Local(), T0, local_node_id=OTHER)
    assert cor.match(resp_from(NODE, 1)) is None
    assert cor.match(resp_from(OTHER, 1)) == "loc"


# --- Parsers ------------------------------------------------------------------
#
# Capturas literales de tools/captures/20260928-083710/ (nodo X1 → T1000-E,
# firmware 2.7.268.dd79d33, 2026-09-28). El texto de NODES/CONFIG/etc. es
# tal cual llegó (reensamblado ya sin separador entre páginas).


def test_parsers_pending_return_raw() -> None:
    for name in PENDING_FORMATS:
        command, *verb = name.split()
        parsed = parse_response(command, "texto tal cual", tuple(verb))
        assert parsed.kind == "raw"
        assert parsed.text == "texto tal cual"


def test_parser_failure_falls_back_to_raw(monkeypatch) -> None:
    def broken(text: str) -> dict:
        raise ValueError("formato inesperado")

    monkeypatch.setitem(PARSERS, "WATCH STATS", broken)
    parsed = parse_response("WATCH", "???", ("stats",))
    assert parsed.command == "WATCH STATS"
    assert parsed.kind == "raw"
    assert "formato inesperado" in (parsed.error or "")


@pytest.mark.parametrize(
    ("command", "text"),
    [
        ("SECURITY", "JT: Unknown command 'SECURITY'"),
        ("STATS", "JT: Unknown command 'STATS'"),
    ],
)
def test_unknown_command_detected_before_any_parser(command: str, text: str) -> None:
    parsed = parse_response(command, text)
    assert parsed.kind == "unsupported"
    assert parsed.data == {"command": command}


def test_parse_version() -> None:
    parsed = parse_response("VERSION", "JT VERSION: 2.7.268.dd79d33")
    assert parsed.kind == "structured"
    assert parsed.data == {"version": "2.7.268.dd79d33"}


def test_parse_version_with_marker() -> None:
    parsed = parse_response("VERSION", "🔴 JT VERSION: 2.8.005.b42309e")
    assert parsed.data == {"version": "2.8.005.b42309e", "marker": "🔴"}


def test_parse_version_accepts_nexus_alias_header() -> None:
    # Firmware viejo (2.7.265, captura real 2026-09-28): cabecera "Nexus"
    # en vez de "JT" — mismo contenido, nomenclatura distinta.
    parsed = parse_response("VERSION", "Nexus VERSION: 2.7.265.30ee5fd")
    assert parsed.kind == "structured"
    assert parsed.data == {"version": "2.7.265.30ee5fd"}


def test_parse_info() -> None:
    text = "JT INFO:\n!af000018 [N019]\nVer: 2.7.268.dd79d33\nRole: MUTE\nMAC: 00:11:22:33:44:55"
    parsed = parse_response("INFO", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "node_id": "!af000018",
        "short_name": "N019",
        "ver": "2.7.268.dd79d33",
        "role": "MUTE",
        "mac": "00:11:22:33:44:55",
    }


def test_parse_info_with_leading_marker() -> None:
    # Captura real (2026-09-28, firmware 2.8.005): el marcador 🟢/🔴
    # (semáforo de firma válida, confirmado por el usuario) también aparece
    # delante de INFO, no solo de VERSION — bug real encontrado y corregido.
    text = (
        "🟢 JT INFO:\n!af000002 [N019]\nVer: 2.8.005.f76ca88\nRole: MUTE\n"
        "MAC: 00:11:22:33:44:55"
    )
    parsed = parse_response("INFO", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "marker": "🟢",
        "node_id": "!af000002",
        "short_name": "N019",
        "ver": "2.8.005.f76ca88",
        "role": "MUTE",
        "mac": "00:11:22:33:44:55",
    }


def test_parse_info_accepts_nexus_alias_header() -> None:
    # Captura real (2026-09-28): un nodo en firmware 2.7.265 respondió con
    # "Nexus INFO:" en vez de "JT INFO:" — antes de este fix caía a "raw" y
    # ese nodo no era detectable como candidato en /nexus/scan.
    text = "Nexus INFO:\n!4133cd33 [🐂]\nVer: 2.7.265.30ee5fd\nRole: CLIENT\nMAC: d1:6b:41:33:cd:33"
    parsed = parse_response("INFO", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "node_id": "!4133cd33",
        "short_name": "🐂",
        "ver": "2.7.265.30ee5fd",
        "role": "CLIENT",
        "mac": "d1:6b:41:33:cd:33",
    }


def test_parse_stats() -> None:
    text = "JT STATS:\nTX:15 RX:117\nBad:30(25%) Dp:11(9%)\nRelay:0 Can:0\nDrop:0 Noise:-109"
    parsed = parse_response("STATS", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "tx": {"value": 15},
        "rx": {"value": 117},
        "bad": {"value": 30, "percent": 25},
        "dp": {"value": 11, "percent": 9},
        "relay": {"value": 0},
        "can": {"value": 0},
        "drop": {"value": 0},
        "noise": {"value": -109},
    }


def test_parse_config() -> None:
    text = (
        "JT CONFIG:\nRole: MUTE\nNI:10900s\nTEL: D:43200s E:3600s P:3600s\n"
        "POS:14400s(264) Smart:1\nGPS:0 Fixed:0 HM:0 RM:0\nLoc: 0.00000,0.00000"
    )
    parsed = parse_response("CONFIG", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "role": "MUTE",
        "ni_seconds": 10900,
        "tel_d_seconds": 43200,
        "tel_e_seconds": 3600,
        "tel_p_seconds": 3600,
        "pos_seconds": 14400,
        "pos_smart_meters": 264,
        "smart": 1,
        "gps": 0,
        "fixed": 0,
        "hm": 0,
        "rm": 0,
        "loc": "0.00000,0.00000",
    }


def test_parse_lora() -> None:
    text = (
        "JT LORA:\nSF:7 BW:62 CR:5\nPreset:0 (OFF)\nFreq:869.6180MHz\n"
        "Power:23dBm\nIgnoreMQTT:0\nRebroadcast:CORE_ONLY"
    )
    parsed = parse_response("LORA", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "sf": 7,
        "bw": 62,
        "cr": 5,
        "freq_mhz": "869.6180",
        "power_dbm": 23,
        "ignore_mqtt": 0,
        "rebroadcast": "CORE_ONLY",
        "preset": 0,
        "preset_label": "OFF",
    }


def test_parse_drops() -> None:
    parsed = parse_response("DROPS", "JT ACTIVE DROPS:\nP_OFF T_OFF ")
    assert parsed.data == {"active": ["P_OFF", "T_OFF"]}


def test_parse_nodes_reassembled_across_page_boundary() -> None:
    # Reproduce exactamente el corte real entre página 1 y 2 de la captura:
    # una entrada partida a mitad de ID de nodo, reconstruida por
    # reassembly.py SIN separador antes de llegar aquí.
    text = "JT NodeDB:\n!af000001:N001:0:14:K+ !af000009:N007:1:14:KV !af000006:N004:0:14:K+"
    parsed = parse_response("NODES", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "nodes": [
            {"node_id": "!af000001", "short_name": "N001", "values": [0, 14], "flags": "K+"},
            {"node_id": "!af000009", "short_name": "N007", "values": [1, 14], "flags": "KV"},
            {"node_id": "!af000006", "short_name": "N004", "values": [0, 14], "flags": "K+"},
        ]
    }


def test_parsers_reject_wrong_header() -> None:
    for command, text in (
        ("VERSION", "algo distinto"),
        ("INFO", "JT STATS:\nTX:1"),
        ("STATS", "JT INFO:\nfoo"),
        ("CONFIG", "no es config"),
        ("LORA", "JT WATCH: ADD"),
        ("DROPS", "JT CONFIG:\nfoo"),
        ("NODES", "JT NodeDB:\nsin entradas reconocibles"),
        ("SECURITY", "no es security"),
        ("SETTINGS", "no es settings"),
        ("FSIG", "no es fsig"),
        ("LORA-STATUS", "no es lora status"),
    ):
        parsed = parse_response(command, text)
        assert parsed.kind == "raw"
        assert parsed.error is not None


# --- Parsers, segunda tanda de capturas -----------------------------------
#
# Capturas literales de tools/captures/20260928-123539/ (nodo X1 → T1000-E,
# ambos ya en firmware 2.8.005, 2026-09-28), copiadas en
# backend/tests/fixtures/nexus/captura-20260928-x1-t1000-security-settings-fsig.*


def test_parse_security() -> None:
    text = (
        "🟢 JT SECURITY:\n REQ_SIG:off\n ALLOW_DM:off\n SILENT:off\n"
        " FAV_NX:off\n FAV_TR:off\n BYPASS_RP:off (28/256)"
    )
    parsed = parse_response("SECURITY", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "marker": "🟢",
        "req_sig": "off",
        "allow_dm": "off",
        "silent": "off",
        "fav_nx": "off",
        "fav_tr": "off",
        "bypass_rp": "off",
        "bypass_rp_extra": "28/256",
    }


def test_parse_settings() -> None:
    text = (
        "🟢 JT SETTINGS:\nRole:MUTE Msk:OFF\nHops:OFF CA:0 BT:0\nBurner:OFF\n"
        "Drops:0x0000000000000000 DMF:0\nPPing:0x002 RS:0 SK:0/4\nBD:5s"
    )
    parsed = parse_response("SETTINGS", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "marker": "🟢",
        "role": "MUTE",
        "msk": "OFF",
        "hops": "OFF",
        "ca": "0",
        "bt": "0",
        "burner": "OFF",
        "drops": "0x0000000000000000",
        "dmf": "0",
        "pping": "0x002",
        "rs": "0",
        "sk": "0/4",
        "bd": "5s",
    }


def test_parse_fsig() -> None:
    # Texto ya reensamblado (reassembly.py quita el "P1: " de cabecera) —
    # la propia respuesta trae otro aviso suelto antes ("JT: Paging
    # signatures...", sin cabecera JT FSIG:, que cae a texto crudo).
    text = "JT Signatures:\nS1: OFF\nS2: OFF\nS3: OFF\nS4: OFF\nS5: OFF\nS6: OFF\nS7: OFF\nS8: OFF"
    parsed = parse_response("FSIG", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "slots": {f"S{n}": {"active": False} for n in range(1, 9)},
    }


def test_parse_fsig_active_slot() -> None:
    # Captura real (2026-09-28): FSIG SET 1 TEST -> FSIG -> FSIG OFF 1,
    # ver docs/design/nexus-control.md §0.7.
    text = "JT Signatures:\nS1: TEST (text) (4B)\nS2: OFF\nS3: OFF\nS4: OFF\nS5: OFF\nS6: OFF\nS7: OFF\nS8: OFF"
    parsed = parse_response("FSIG", text)
    assert parsed.kind == "structured"
    assert parsed.data["slots"]["S1"] == {"active": True, "pattern": "TEST", "encoding": "text", "bytes": 4}
    assert parsed.data["slots"]["S2"] == {"active": False}


def test_parse_fsig_priming_notice_is_not_structured() -> None:
    parsed = parse_response("FSIG", "🟢 JT: Paging signatures...")
    assert parsed.kind == "raw"


def test_parse_lora_status() -> None:
    text = (
        "🟢 JT LORA Status:\nFreq: 869.618MHz\nBW:62.50kHz SF:7 CR:5\n"
        "Pre:16 (32ms)\nSlot:12ms CW:3-8\nSW:0x2B\nChipPwr:22dBm\nSpeed:2734 b/s"
    )
    parsed = parse_response("LORA-STATUS", text)
    assert parsed.kind == "structured"
    assert parsed.data == {
        "marker": "🟢",
        "freq_mhz": "869.618",
        "bw_khz": "62.50",
        "sf": 7,
        "cr": 5,
        "preamble_symbols": 16,
        "preamble_ms": 32,
        "slot_ms": 12,
        "cw": "3-8",
        "sync_word": "0x2B",
        "chip_power_dbm": 22,
        "speed_bps": 2734,
    }


def test_parse_watch_stats_with_target() -> None:
    # Captura real reensamblada (2026-09-28), confirmada por el usuario
    # probando en directo con hardware: WATCH STATS exige el node_id como
    # argumento; sin él solo devuelve el mensaje de uso.
    text = (
        "JT Watch Stats:\n"
        "Target: af000001\n"
        "Pkts: 10 Bytes: 308\n"
        "RF (Direct Only):\n"
        "Avg:-4dB SNR:14.1 FE:0\n"
        "SD: 2.9 SNR:0.2 FE:0\n"
        "Min:-7dB SNR:13.8 FE:0\n"
        "Max:0dB SNR:14.5 FE:0\n"
        "Hops: h0:10 h1:0 h2:0 h3:0 h4:0\n"
        "Relay: Last:90 Primary:90 (10)\n"
        "Timing: Min:4s Max:130s Age:0s\n"
        "Ports: NI:0 POS:0 TEL:0 TXT:10 ADM:0 RT:0 OTH:0\n"
    )
    parsed = parse_response("WATCH", text, ("STATS", "!af000001"))
    assert parsed.command == "WATCH STATS"
    assert parsed.kind == "structured"
    assert parsed.data == {
        "target": "!af000001",
        "pkts": 10,
        "bytes": 308,
        "rf": {
            "avg": {"db": -4, "snr": 14.1, "fe": 0},
            "sd": {"value": 2.9, "snr": 0.2, "fe": 0},
            "min": {"db": -7, "snr": 13.8, "fe": 0},
            "max": {"db": 0, "snr": 14.5, "fe": 0},
        },
        "hops": {"h0": 10, "h1": 0, "h2": 0, "h3": 0, "h4": 0},
        "relay": {"last": 90, "primary": 90, "primary_extra": 10},
        "timing": {"min_seconds": 4, "max_seconds": 130, "age_seconds": 0},
        "ports": {"ni": 0, "pos": 0, "tel": 0, "txt": 10, "adm": 0, "rt": 0, "oth": 0},
    }


def test_parse_watch_stats_rejects_wrong_header() -> None:
    parsed = parse_response("WATCH", "no es watch stats", ("STATS", "!af000001"))
    assert parsed.kind == "raw"
    assert parsed.error is not None


# --- FAVS/IGNORED/FAV/UNFAV -------------------------------------------------
#
# Captura real (2026-09-28), backend/tests/fixtures/nexus/
# captura-20260928-x1-t1000-favs.{md,jsonl} — misma sesión en la que se
# preguntó si favoritos/ignorados era "solicitable" desde Nexus.


def test_parse_favs() -> None:
    text = (
        "JT Favorites:\n"
        "!af000004:N002 !af000005:N003 !af000001:N001 !af000006:N004 !af000007:N005 "
        "!af000008:N006 !af000009:N007 !af00000a:N008 !af00000b:N009 !af00000c:N010 "
        "!af00000d:N011 !af000015:N018 !af00000e:N001 !af00000f:N012 !af000010:N013 "
        "!af000011:N014 !af000012:N015 !af000013:N016 !af000014:N017 "
    )
    parsed = parse_response("FAVS", text)
    assert parsed.kind == "structured"
    assert len(parsed.data["entries"]) == 19
    assert parsed.data["entries"][0] == {"node_id": "!af000004", "short_name": "N002"}
    assert parsed.data["entries"][2] == {"node_id": "!af000001", "short_name": "N001"}
    assert parsed.data["entries"][-1] == {"node_id": "!af000014", "short_name": "N017"}
    # Nombre corto con emoji: no confunde el regex con separador.
    assert {"node_id": "!af000013", "short_name": "N016"} in parsed.data["entries"]


def test_parse_favs_marker() -> None:
    parsed = parse_response("FAVS", "🟢 JT Favorites:\n!af000004:N002 ")
    assert parsed.data["marker"] == "🟢"
    assert parsed.data["entries"] == [{"node_id": "!af000004", "short_name": "N002"}]


def test_parse_ignored_empty() -> None:
    # Captura real: sin ningún nodo ignorado, respondió "JT Ignored:\n" (sin
    # entradas) — confirmado, no un fallo de parser.
    parsed = parse_response("IGNORED", "JT Ignored:\n")
    assert parsed.kind == "structured"
    assert parsed.data == {"entries": []}


def test_parse_fav_updated() -> None:
    parsed = parse_response("FAV", "🟢 JT: Updated node !af000001 (N001)", ("!af000001",))
    assert parsed.kind == "structured"
    assert parsed.data == {"node_id": "!af000001", "short_name": "N001", "marker": "🟢"}


def test_parse_unfav_updated() -> None:
    # FAV y UNFAV confirman con el mismo texto genérico — no distinguen
    # add/quitar en el propio mensaje (confirmado real, no una limitación
    # del parser).
    parsed = parse_response("UNFAV", "🟢 JT: Updated node !af000001 (N001)", ("!af000001",))
    assert parsed.kind == "structured"
    assert parsed.data["node_id"] == "!af000001"


def test_ignore_unignore_have_no_parser_yet() -> None:
    # Deliberado: solo FAV/UNFAV se probaron contra hardware real. Asumir
    # que IGNORE/UNIGNORE comparten formato sin haberlo visto sería
    # inventar — se quedan como texto crudo hasta confirmarlo.
    for command in ("IGNORE", "UNIGNORE"):
        parsed = parse_response(command, "JT: Updated node !af000001 (N001)", ("!af000001",))
        assert parsed.kind == "raw"


# --- ZH (Zero Hop) ---------------------------------------------------------
#
# Captura real (2026-09-28), backend/tests/fixtures/nexus/
# captura-20260928-x1-t1000-zh.{md,jsonl} — pedido explícito del usuario:
# destacar el Zero Hop igual que favoritos/ignorados. Argumento SIEMPRE
# pre-truncado a los 2 últimos hex por `addressing.zero_hop_suffix` antes
# de llegar aquí (confirmado el usuario: "el ZH es sólo con los dos
# últimos dígitos del ID") — una primera prueba con el id sin truncar
# (fuera del pipeline real) dio un resultado distinto y se descartó.


def test_parse_zh_list_empty() -> None:
    parsed = parse_response("ZH", "🟢 JT: ZH List is EMPTY", ("LIST",))
    assert parsed.command == "ZH LIST"
    assert parsed.kind == "structured"
    assert parsed.data == {"entries": [], "marker": "🟢"}


def test_parse_zh_list_with_entry() -> None:
    parsed = parse_response("ZH", "🟢 ZH List:\n[90] N001,N043\n", ("LIST",))
    assert parsed.kind == "structured"
    assert parsed.data == {
        "entries": [{"zh_id": "90", "short_name": "N001", "extra": "N043"}],
        "marker": "🟢",
    }


def test_parse_zh_add() -> None:
    parsed = parse_response("ZH", "🟢 JT: ZH ID 0x90 ADDED", ("ADD", "90"))
    assert parsed.command == "ZH ADD"
    assert parsed.kind == "structured"
    assert parsed.data == {"zh_id": "90", "action": "ADDED", "marker": "🟢"}


def test_parse_zh_del() -> None:
    parsed = parse_response("ZH", "🟢 JT: ZH ID 0x90 REMOVED", ("DEL", "90"))
    assert parsed.command == "ZH DEL"
    assert parsed.kind == "structured"
    assert parsed.data == {"zh_id": "90", "action": "REMOVED", "marker": "🟢"}


def test_parse_firewallstats() -> None:
    # Captura real reensamblada (2026-09-28, nodo X1 -> T1000-E, firmware
    # 2.7.268), backend/tests/fixtures/nexus/captura-20260928-x1-t1000.md,
    # comando FIREWALLSTATS.
    text = (
        "JT Firewall Stats:\n"
        "Processed: 145\n"
        "Bypass: 21 (14.5%)  NXS:21 FAV:0\n"
        "Drop:   0 (0.0%)\n"
        "Accept: 124 (85.5%)\n"
        "PKI: 0 (L:0 R:0)  PRIV: 0  WL: 0  BL: 0\n"
        "Relay: 0  IDR: 0\n"
        "HOP: 6:0 7:0  PRE: 0  ACKS: 0\n"
        "Req: NI:0 PO:0 TL:0\n"
        "BReq: NI:0 PO:0 TL:0\n"
        "Port: NI:0 PO:0 TL:0\n"
        "Port: NB:0 TR:0 SF:0\n"
        "Port: AD:0 TX:0 KV:0 AL:0 WP:0\n"
        "TL Sub: Dev:0 Pwr:0 Env:0 Oth:0\n"
        "POS Src: Man:0 GPS:0 Oth:0  NoMQTT: 0\n"
        "Trace Loc:0 Rem:0\n"
        "Trace Dir:0 (L:0 R:0)\n"
        "Vanilla Ignore: 0  Nexus-Ignored: 0\n"
        "OUT Drop: NI:0 PO:0 TL:0 TR:0 AD:0 RO:0\n"
        "Sig Drop: 0\n"
        "RL Seen: TX:0 TR:0 OT:0\n"
        "RL Seen: NI:0 PO:0 TL:0 PR:0\n"
        "RL Pass: TX:0 TR:0 OT:0\n"
        "RL Pass: NI:0 PO:0 TL:0 PR:0\n"
        "RL Drop: TX:0 TR:0 OT:0\n"
        "RL Drop: NI:0 PO:0 TL:0 PR:0\n"
    )
    parsed = parse_response("FIREWALLSTATS", text)
    assert parsed.kind == "structured"
    assert parsed.data["processed"] == {"value": 145}
    assert parsed.data["bypass"] == {"value": 21, "percent": 14.5}
    assert parsed.data["nxs"] == {"value": 21}
    assert parsed.data["fav"] == {"value": 0}
    assert parsed.data["drop"] == {"value": 0, "percent": 0.0}
    assert parsed.data["accept"] == {"value": 124, "percent": 85.5}
    assert parsed.data["pki"] == {"value": 0}
    assert parsed.data["l"] == {"value": 0}
    assert parsed.data["r"] == {"value": 0}
    assert parsed.data["priv"] == {"value": 0}
    assert parsed.data["wl"] == {"value": 0}
    assert parsed.data["bl"] == {"value": 0}
    assert parsed.data["relay"] == {"value": 0}
    assert parsed.data["idr"] == {"value": 0}
    # Texto crudo conservado íntegro (nunca se pierde nada).
    assert "Port: NI:0 PO:0 TL:0" in parsed.data["extra_raw"]
    assert "RL Drop: NI:0 PO:0 TL:0 PR:0" in parsed.data["extra_raw"]
    assert "processed" not in parsed.data["extra_raw"].lower()
    # Etiquetas repetidas (Port ×3, RL Seen/Pass/Drop ×2 cada una, Trace ×2)
    # se resuelven SIN colisión: cada línea es su propia entrada de
    # extra_sections, en orden, nunca fusionadas entre sí.
    sections = parsed.data["extra_sections"]
    assert [s["label"] for s in sections] == [
        "HOP", "Req", "BReq", "Port", "Port", "Port", "TL Sub", "POS Src",
        "Trace Loc", "Trace Dir", "Vanilla Ignore", "OUT Drop", "Sig Drop",
        "RL Seen", "RL Seen", "RL Pass", "RL Pass", "RL Drop", "RL Drop",
    ]
    # HOP: "6:0"/"7:0" son pares compuestos (un número seguido de ":"), no
    # se puede saber si ese número es un valor suelto o una clave sin
    # adivinar — se descartan de los campos a propósito, quedan solo en
    # "raw"; PRE/ACKS sí son inequívocos y se capturan.
    assert sections[0] == {"label": "HOP", "fields": {"pre": 0, "acks": 0}, "raw": "HOP: 6:0 7:0  PRE: 0  ACKS: 0"}
    # Las 3 líneas "Port:" tienen conjuntos de campos DISTINTOS cada vez —
    # nunca colisionan aunque compartan etiqueta.
    assert sections[3]["fields"] == {"ni": 0, "po": 0, "tl": 0}
    assert sections[4]["fields"] == {"nb": 0, "tr": 0, "sf": 0}
    assert sections[5]["fields"] == {"ad": 0, "tx": 0, "kv": 0, "al": 0, "wp": 0}
    # Las 2 líneas "RL Pass:" tampoco colisionan entre sí (separadas por
    # posición, no por nombre inventado).
    assert sections[15]["fields"] == {"tx": 0, "tr": 0, "ot": 0}
    assert sections[16]["fields"] == {"ni": 0, "po": 0, "tl": 0, "pr": 0}
    # Paréntesis con sub-claves (Trace Dir) y guiones en la clave
    # (Nexus-Ignored) también se capturan sin inventar nada.
    assert sections[9] == {
        "label": "Trace Dir", "fields": {"dir": 0, "l": 0, "r": 0}, "raw": "Trace Dir:0 (L:0 R:0)"
    }
    assert sections[10]["fields"] == {"ignore": 0, "nexus-ignored": 0}


def test_parse_firewallstats_rejects_wrong_header() -> None:
    parsed = parse_response("FIREWALLSTATS", "no es firewallstats")
    assert parsed.kind == "raw"
    assert parsed.error is not None


def test_parse_watch_list_empty() -> None:
    parsed = parse_response("WATCH", "🟢 JT: Watchlist empty.", ("LIST",))
    assert parsed.kind == "structured"
    assert parsed.data == {"entries": [], "marker": "🟢"}


def test_parse_watch_list_with_entries() -> None:
    # Captura real: SIN el prefijo "JT:" que llevan las demás respuestas de
    # este subsistema (confirmado, no es un error de transcripción).
    parsed = parse_response("WATCH", "🟢 Watchlist: af000001[N001]", ("LIST",))
    assert parsed.kind == "structured"
    assert parsed.data == {"entries": [{"node_id": "!af000001", "short_name": "N001"}], "marker": "🟢"}


def test_parse_watch_add() -> None:
    parsed = parse_response("WATCH", "🟢 JT: Added af000001 to watchlist.", ("ADD", "!af000001"))
    assert parsed.kind == "structured"
    assert parsed.data == {"added": "!af000001", "marker": "🟢"}


def test_parse_watch_del() -> None:
    parsed = parse_response("WATCH", "🟢 JT: Removed af000001.", ("DEL", "!af000001"))
    assert parsed.kind == "structured"
    assert parsed.data == {"removed": "!af000001", "marker": "🟢"}


def test_watch_stats_without_target_arg_falls_back_to_raw() -> None:
    # Captura real: "WATCH STATS" SIN el node_id como argumento responde el
    # mensaje de uso genérico, no una tabla — el parser de WATCH STATS
    # exige esa cabecera ("JT Watch Stats:") y aquí no aparece, así que cae
    # a texto crudo con un error de parseo, no a "sin parser registrado".
    parsed = parse_response("WATCH", "🟢 JT WATCH: ADD|DEL|LIST|CLEAR|RESET|STATS|ALL", ("STATS",))
    assert parsed.kind == "raw"
    assert parsed.command == "WATCH STATS"
    assert parsed.error is not None


# --- Aislamiento --------------------------------------------------------------


def test_module_is_pure() -> None:
    """Sin adaptadores, BD, FastAPI ni librería meshtastic: testeable aislado."""
    package = Path(catalog.__file__).parent
    forbidden = ("noc.adapters", "sqlalchemy", "fastapi", "meshtastic", "redis", "httpx")
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [
                    a.name for a in node.names
                ]
                for name in names:
                    assert not name.startswith(forbidden), f"{path.name} importa {name}"
