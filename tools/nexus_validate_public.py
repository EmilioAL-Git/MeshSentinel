"""Batería de validación contra firmware JenTastic-Nexus PÚBLICO (2.8.1xx).

Herramienta de desarrollo, fuera del backend/gateway. Comprueba en hardware real
las hipótesis del estudio `docs/design/nexus-firmware-publico-estudio.md`
(H1-H10, O1-O6) con DOS nodos por USB:

- EMISOR: manda los `/nexus ...` por su canal de confianza (`Nexus`/`JenT`).
- OBJETIVO: el nodo bajo prueba (se le habla con -node/-mac/-device/-local).

Cada prueba da un veredicto:
  PASS          el firmware se comporta como predice el estudio.
  FAIL          responde, pero NO como predice el estudio (hipótesis refutada).
  INCONCLUSIVE  sin respuesta / datos insuficientes (no prueba nada).
  INFO          captura sin aserción (material para parsers nuevos).

FASES (`--phases`, por defecto `read,addr`); cada una es acumulable:
  read      solo lectura: formatos, marcador de firma, comandos nuevos.   [seguro]
  addr      direccionamiento (-node/-mac/-device), pacing, redirect.      [seguro]
  capture   captura de comandos nuevos para parsers (vecinos, TRACE…).    [seguro,
            pero NETSCAN/CLIENTSCAN gastan aire: van con --active-scan]
  mutate    cambios REVERSIBLES (INVALID, DROP, ZH, NIGN, GROUP) con
            reversión y verificación final del estado.                    [reversible]
  security  (sin pruebas automáticas; validado a mano, ver estudio §7)

NOTA: `/nexus-local` mandado por la API serie NO responde ni aplica (2.7.268
y 2.8.101), así que ninguna reversión usa `-local`: todas van por la malla
(`-node`) mientras `REQ_SIG` esté apagado.

Requisitos: gateway nativo que use esos puertos PARADO; `findPorts` descubre los
dos nodos. Nunca se hace SAVE: todo cambio vive en RAM y un reinicio lo limpia.

    arch -arm64 .venv/bin/python tools/nexus_validate_public.py --self-test
    arch -arm64 .venv/bin/python tools/nexus_validate_public.py
    arch -arm64 .venv/bin/python tools/nexus_validate_public.py \
        --phases read,addr,capture,mutate --sender /dev/cu.usbmodem1101 \
        --target-port /dev/cu.usbmodem101
    arch -arm64 .venv/bin/python tools/nexus_validate_public.py --phases security
    arch -arm64 .venv/bin/python tools/nexus_validate_public.py --only H1,H2

Salida en tools/captures/validate-<fecha>/: results.jsonl, report.md y
replies.jsonl (todo el texto oído, tal cual, por si hay que escribir parsers).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

MARKERS = "🔒🟢🟠🔴"
TRUSTED_CHANNEL_NAMES = ("nexus", "jent", "nexus2")
PAGE_RE = re.compile(r"^P(\d+):\s?(.*)$", re.DOTALL)

# ------------------------------------------------------------------ puros --


@dataclass(frozen=True)
class Reply:
    at: float
    heard_by: str  # "sender" | "target"
    from_id: str | None
    channel: int
    packet_id: int | None
    text: str


@dataclass
class Assembled:
    body: str  # texto reensamblado (páginas concatenadas SIN separador)
    marker: str | None  # 🔒🟢🟠🔴 de la primera respuesta
    messages: int
    pages: int
    notices: list[str] = field(default_factory=list)


def split_marker(text: str) -> tuple[str | None, str]:
    text = text.lstrip()
    if text and text[0] in MARKERS:
        return text[0], text[1:].lstrip()
    return None, text


def assemble(replies: list[Reply], dedupe_s: float = 10.0) -> Assembled:
    """Colapsa duplicados (copia local + malla), reensambla `P<n>:` sin separador."""
    seen: dict[tuple[str | None, str], float] = {}
    kept: list[Reply] = []
    for r in sorted(replies, key=lambda x: x.at):
        key = (r.from_id, r.text)
        if key in seen and r.at - seen[key] <= dedupe_s:
            continue
        seen[key] = r.at
        kept.append(r)
    marker: str | None = None
    pages: list[str] = []
    others: list[str] = []
    notices: list[str] = []
    for r in kept:
        m, rest = split_marker(r.text)
        if marker is None and m is not None:
            marker = m
        pm = PAGE_RE.match(rest)
        if pm:
            pages.append(pm.group(2))
        elif re.match(r"^JT:\s*Paging\b", rest):
            notices.append(rest)
        else:
            others.append(rest)
    body = "\n".join(others)
    if pages:
        body = (body + "\n" if body else "") + "".join(pages)
    return Assembled(body, marker, len(kept), len(pages), notices)


def mac_forms(mac: str) -> dict[str, str]:
    """`aa:bb:cc:dd:ee:ff` -> mac4 (últimos 2 bytes, lo que el firmware compara)."""
    raw = mac.replace(":", "").lower()
    return {"mac4": raw[-4:], "mac6": raw[-6:], "mac12": raw}


Status = str  # PASS | FAIL | INCONCLUSIVE | INFO
Check = Callable[[Assembled, dict[str, str]], tuple[Status, str]]


def evaluate(a: Assembled | None, expect: tuple[str, ...], forbid: tuple[str, ...],
             silence: bool) -> tuple[Status, str]:
    if a is None or a.messages == 0:
        if silence:
            return "PASS", "sin respuesta, como se esperaba"
        return "INCONCLUSIVE", "sin respuesta"
    if silence:
        return "FAIL", f"respondió ({a.messages} msg) y se esperaba silencio: {a.body[:80]!r}"
    for pat in expect:
        if not re.search(pat, a.body, re.S | re.I):
            return "FAIL", f"no casa /{pat}/ en {a.body[:120]!r}"
    for pat in forbid:
        if re.search(pat, a.body, re.S | re.I):
            return "FAIL", f"aparece lo prohibido /{pat}/ en {a.body[:120]!r}"
    return "PASS", "ok"


# ------------------------------------------------------------- definición --


@dataclass
class Step:
    cmd: str  # plantilla: {target_short} {sender_id} {mac4} … y {var} capturadas
    via: str = "node"  # node|device|mac4|mac6|broadcast|local_target|local_sender|raw
    expect: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    silence: bool = False
    wait: float | None = None  # máx. de espera (s); None = por defecto
    capture: dict[str, str] = field(default_factory=dict)  # var -> regex (grupo 1)
    check: Check | None = None
    note: str = ""
    count_replies: bool = False  # para pacing: cuenta paquetes distintos


@dataclass
class Test:
    id: str
    phase: str
    hypo: str
    title: str
    steps: list[Step]
    restore: list[Step] = field(default_factory=list)
    risky: bool = False
    # Recibe la foto inicial del estado; devuelve el motivo para SALTARSE la prueba
    # (p. ej. la regla ya estaba activa: la reversión la dejaría distinta).
    guard: Callable[[dict[str, str]], str | None] | None = None


def _truncation_check(a: Assembled, v: dict[str, str]) -> tuple[Status, str]:
    n_total = int(v.get("db_nodes", "0") or 0)
    rows = len(re.findall(r"!?[0-9a-f]{8}\s*:", a.body))
    if n_total == 0:
        return "INCONCLUSIVE", "no se obtuvo el total de DBINFO"
    if rows < n_total and len(a.body) >= 1500:
        return "PASS", (f"truncada: {rows} filas de {n_total} nodos, {len(a.body)} B "
                        "(H5 confirmada: el firmware no avisa)")
    if rows >= n_total:
        return "INCONCLUSIVE", f"cabe entera ({rows}/{n_total}); probar con una NodeDB mayor"
    return "FAIL", f"faltan filas ({rows}/{n_total}) pero solo {len(a.body)} B: ¿otro motivo?"


def _marker_info(a: Assembled, v: dict[str, str]) -> tuple[Status, str]:
    names = {"🔒": "firmado+confianza", "🟢": "firmado verificado, no confiable",
             "🟠": "firma presente pero inválida", "🔴": "sin firma"}
    if a.marker is None:
        return "FAIL", f"sin marcador delante: {a.body[:60]!r}"
    return "INFO", f"marcador {a.marker} = {names[a.marker]}"


def _nodecrc_check(a: Assembled, v: dict[str, str]) -> tuple[Status, str]:
    want = v.get("sender_id", "")[1:].lower()
    if want and want in a.body.lower():
        return "PASS", f"NODECRC devuelve el node_num del emisor ({want}): fórmula crc32 confirmada"
    return "FAIL", f"no aparece {want} en {a.body[:100]!r}"


def _security_guard(snap: dict[str, str]) -> str | None:
    """No tocar seguridad si ya hay REQ_SIG o claves secundarias: la reversión
    (RSIG OFF / SKEY 1 OFF) destruiría configuración REAL del operador."""
    if re.search(r"REQ_SIG:\s*ON", snap.get("SECURITY", ""), re.I):
        return "el objetivo ya tiene REQ_SIG ON"
    m = re.search(r"SK:(\d+)/4", snap.get("SETTINGS", ""))
    if m is None:
        return "no se pudo leer SETTINGS (SK:n/4)"
    if m.group(1) != "0":
        return f"el objetivo ya tiene {m.group(1)} clave(s) secundaria(s) (SKEY)"
    return None


def build_tests() -> list[Test]:
    T: list[Test] = []
    add = T.append

    # ---------------------------------------------------------------- read
    add(Test("R1", "read", "H3", "Marcador de firma de la respuesta", [
        Step("INFO", expect=(r"JT INFO",), check=_marker_info,
             capture={"mac": r"MAC:\s*([0-9a-fA-F:]{17})", "fw": r"Ver:\s*(\S+)",
                      "role_name": r"Role:\s*(\S+)"}),
    ]))
    add(Test("R2", "read", "H6", "SECURITY trae FAV_XT y 7 líneas", [
        Step("SECURITY", expect=(r"REQ_SIG", r"ALLOW_DM", r"FAV_XT:\S+\s+ch\d", r"BYPASS_RP"),
             capture={"req_sig": r"REQ_SIG:(\S+)"}),
    ]))
    add(Test("R3", "read", "H1", "INVALIDS (consulta) responde con las 5 reglas", [
        Step("INVALIDS", expect=(r"JT INVALID Rules", r"NULL:", r"SPAIN:", r"GERM:", r"HW:", r"ID:")),
    ]))
    add(Test("R4", "read", "H4", "ROLE (lectura) y valor numérico", [
        Step("ROLE", expect=(r"JT ROLE:\s*\S+\s*\((\d+)\)",), capture={"role_num": r"JT ROLE:\s*\S+\s*\((\d+)\)"}),
    ]))
    add(Test("R5", "read", "H8", "Comandos públicos ausentes del catálogo: existen", [
        Step("LCS", expect=(r"JT LCS",), wait=40),
        Step("METRICS {sender_id}", expect=(r"JT METRICS|No metrics",)),
        Step("CHECKSIG", expect=(r"CHECKSIG",)),
        Step("RLS", expect=(r"Paging|RL",), wait=40),
        Step("CHANNELS", expect=(r"JT CHANNELS|JT CHASH",)),
        Step("IGNORMQTT", expect=(r"Ignore MQTT",)),
        Step("OKMQTT", expect=(r"OKTOMQTT",)),
    ]))
    add(Test("R6", "read", "H8", "NODECRC calcula el node_num 2.8 = crc32(clave pública)", [
        Step("NODECRC {sender_pubkey}", check=_nodecrc_check),
    ]))
    add(Test("R7", "read", "H4", "SETROLE/SETLORA bare = 'Unknown command' (falso negativo de 29/09)", [
        Step("SETROLE", expect=(r"Unknown command",)),
        Step("SETLORA", expect=(r"Unknown command",)),
        Step("SETLORA 99 62 5 869.618", expect=(r"Invalid sub-GHz params",),
             note="con argumento INVÁLIDO: prueba que existe y NO aplica nada"),
        Step("SETROLE ZZZ", expect=(r"Invalid role",), note="idem: existe, no aplica"),
    ]))
    add(Test("R8", "read", "H5", "NODES truncado: filas vs total de DBINFO", [
        Step("DBINFO", expect=(r"Nodes:\s*(\d+)",), capture={"db_nodes": r"Nodes:\s*(\d+)"}),
        Step("NODES", wait=150, check=_truncation_check),
    ]))
    # H7 (comandos privados) NO se prueba en hardware: los nodos de prueba corren
    # la build PRIVADA, donde REVERT borra la identidad y FAKENODE/FTEXT inyectan
    # tráfico falso. Se confirma solo por el código fuente.
    add(Test("R9", "read", "H7", "COMPILATION: qué build corre el objetivo", [
        Step("COMPILATION", expect=(r"JT COMPILATION",),
             check=lambda a, v: ("INFO", a.body.replace("\n", " | ")[:200])),
    ]))
    add(Test("R10", "read", "H9", "Nombres de DROPS ≠ alias de DROP (no traducir)", [
        Step("DROPS", expect=(r"JT ACTIVE DROPS",)),
    ]))

    # ---------------------------------------------------------------- addr
    add(Test("A1", "addr", "H2", "-mac con 4 hex (2 bytes) SÍ responde", [
        Step("VERSION", via="mac4", expect=(r"JT VERSION",)),
    ]))
    add(Test("A2", "addr", "H2", "-mac con 6 hex (3 bytes) NO responde", [
        Step("VERSION", via="mac6", silence=True, wait=25),
    ]))
    add(Test("A3", "addr", "H10", "-node es insensible a mayúsculas", [
        Step("VERSION", via="node_lower", expect=(r"JT VERSION",)),
    ]))
    add(Test("A4", "addr", "—", "-device !id responde (id vigente)", [
        Step("VERSION", via="device", expect=(r"JT VERSION",)),
    ]))
    add(Test("A5", "addr", "pacing", "Difusión: 2.º comando a 1 s se descarta (5 s)", [
        Step("VERSION", via="burst2_broadcast", count_replies=True, wait=45,
             check=lambda a, v: (("PASS", f"{v.get('_n')} respuesta(s) del objetivo: 1 esperada")
                                 if v.get("_n") == "1" else
                                 ("FAIL", f"{v.get('_n')} respuestas del objetivo (esperada 1)"))),
    ]))
    add(Test("A6", "addr", "pacing", "Dirigido: 2 comandos a 1 s se atienden los dos", [
        Step("VERSION|UPTIME", via="burst2_node", count_replies=True, wait=60,
             check=lambda a, v: (("PASS", "2 respuestas: el dirigido salta el cooldown")
                                 if v.get("_n") == "2" else
                                 ("FAIL", f"{v.get('_n')} respuestas (esperadas 2)"))),
    ]))
    add(Test("A7", "addr", "H9", "R: 1 nivel funciona; anidado (2+) no se procesa en esta build", [
        Step("R DM {sender_id} VERSION", expect=(r"JT VERSION",), note="1 nivel"),
        Step("R DM {sender_id} R DM {sender_id} VERSION",
             expect=(r"JT VERSION|depth exceeded",), note="2 niveles"),
        Step("R CH 7 VERSION", expect=(r"JT VERSION",), note="1 nivel por canal"),
    ]))
    add(Test("A8", "addr", "H3", "Marcador en respuesta dirigida y en difusión", [
        Step("VERSION", check=_marker_info),
        Step("VERSION", via="broadcast", check=_marker_info),
    ]))

    # ------------------------------------------------------------- capture
    for n, cmd, wait in (
        ("C1", "NEIGHBORS", 90), ("C2", "INFRA", 90), ("C3", "NODES28", 150),
        ("C4", "HOPSTATS", 40), ("C5", "RELAYS", 90), ("C6", "LCS", 40),
        ("C7", "METRICS {sender_id}", 40), ("C8", "HOPMATRIX", 90),
        ("C9", "FULLCONFIGDUMP", 240), ("C10", "SENSORS", 90), ("C11", "TRUSTED", 30),
        ("C12", "FEATURES", 30), ("C13", "VAULT", 30), ("C14", "MODULES", 90),
    ):
        add(Test(n, "capture", "O1/O4", f"Captura {cmd.split()[0]} (material para parser)",
                 [Step(cmd, wait=wait, check=lambda a, v: ("INFO", f"{a.messages} msg, {len(a.body)} B"))]))
    add(Test("C15", "capture", "O2", "TRACE desde el objetivo hacia el emisor (asíncrono)", [
        Step("TRACE {sender_id}", wait=120, expect=(r"Starting trace|JT TRACE",),
             note="el resultado llega como segundo mensaje `JT TRACE (<s>s):`"),
    ]))
    add(Test("C16", "capture", "O1", "NETSCAN 60 s (gasta aire: solo con --active-scan)", [
        Step("NETSCAN", wait=150),
    ], risky=True))
    add(Test("C17", "capture", "O1", "CLIENTSCAN (gasta aire: solo con --active-scan)", [
        Step("CLIENTSCAN 30", wait=100),
    ], risky=True))

    # -------------------------------------------------------------- mutate
    add(Test("M1", "mutate", "H1", "INVALIDS <R> ON NO existe; INVALID/UNINVALID sí", [
        Step("INVALIDS NULL ON", expect=(r"Unknown command",), note="reproduce el bug H1"),
        Step("INVALID NULL", expect=(r"INVALID NULL ACTIVE",)),
        Step("INVALIDS", expect=(r"NULL:ON",)),
        Step("UNINVALID NULL", expect=(r"INVALID NULL DISABLED",)),
        Step("INVALIDS", expect=(r"NULL:OFF",)),
    ], restore=[Step("UNINVALID NULL", via="node")],
        guard=lambda snap: "NULL ya estaba ON" if re.search(r"NULL:ON", snap.get("INVALIDS", "")) else None))
    add(Test("M2", "mutate", "H1", "INV <R> / UNINV <R> (alias del firmware)", [
        Step("INV SPAIN", expect=(r"INVALID SPAIN ACTIVE",)),
        Step("UNINV SPAIN", expect=(r"INVALID SPAIN DISABLED",)),
    ], restore=[Step("UNINVALID SPAIN", via="node")],
        guard=lambda snap: "SPAIN ya estaba ON" if re.search(r"SPAIN:ON", snap.get("INVALIDS", "")) else None))
    add(Test("M3", "mutate", "H10", "DROP/UNDROP y etiquetas de salida de DROPS", [
        Step("DROP TR", expect=(r"TR filter ACTIVE",)),
        Step("DROPS", expect=(r"\bTR\b",)),
        Step("UNDROP TR", expect=(r"TR filter DISABLED",)),
        Step("DROPS", forbid=(r"\bTR\b",)),
    ], restore=[Step("UNDROP TR", via="node")],
        guard=lambda snap: "TR ya estaba en DROPS" if re.search(r"\bTR\b", snap.get("DROPS", "")) else None))
    add(Test("M4", "mutate", "—", "ZH ADD/DEL con 2 últimos hex", [
        Step("ZH ADD ee", expect=(r"ZH ID 0xEE ADDED",)),
        Step("ZH LIST", expect=(r"\[EE\]|ZH List",)),
        Step("ZH DEL ee", expect=(r"ZH ID 0xEE REMOVED",)),
    ], restore=[Step("ZH DEL ee", via="node")],
        guard=lambda snap: "[EE] ya estaba en ZH" if re.search(r"\[EE\]", snap.get("ZH LIST", ""), re.I) else None))
    add(Test("M5", "mutate", "H5", "NIGN ADD/REM de un id ficticio", [
        Step("NIGN ADD !deadbee1", expect=(r"ADDED to ignores|list full",)),
        Step("NIGN", expect=(r"deadbee1", )),
        Step("NIGN REM !deadbee1", expect=(r"REMOVED",)),
    ], restore=[Step("NIGN REM !deadbee1", via="node")]))
    add(Test("M6", "mutate", "—", "GROUP ADD/REM y direccionamiento por grupo", [
        Step("GROUP ADD zzvt", expect=(r"ADDED to slot",)),
        Step("VERSION", via="group:zzvt", expect=(r"JT VERSION",)),
        Step("GROUP REM zzvt", expect=(r"REMOVED",)),
    ], restore=[Step("GROUP REM zzvt", via="node")]))
    add(Test("M7", "mutate", "H4", "SETROLE con el MISMO rol actual (idempotente; puede reiniciar)", [
        Step("SETROLE {role_num}", expect=(r"Role updated",), wait=40),
    ], risky=True))

    # ------------------------------------------------------------ security
    # S1/S2 (REQ_SIG, SKEY, marcador 🔒, rechazo) se validaron a mano el
    # 2026-10-14 (estudio §7) con una secuencia por la malla y reversión por
    # reinicio USB del objetivo: `/nexus-local` mandado por la API serie NO
    # responde ni aplica (ver más abajo), así que la reversión "local" que
    # tenían aquí no existía. No se automatizan: un fallo dejaría el nodo en
    # REQ_SIG ON hasta reiniciarlo.

    return T


# --------------------------------------------------------------- hardware --


class Runner:
    def __init__(self, sender: Any, target: Any, s: dict[str, Any], t: dict[str, Any],
                 channel: int, out_dir: Path, args: argparse.Namespace) -> None:
        self.sender, self.target = sender, target
        self.s, self.t = s, t
        self.channel = channel
        self.out = out_dir
        self.args = args
        self.replies: list[Reply] = []
        self.lock = threading.Lock()
        self.last_rx = 0.0
        self.vars: dict[str, str] = {
            "target_short": t["short_name"], "target_id": t["node_id"],
            "sender_short": s["short_name"], "sender_id": s["node_id"],
            "sender_pubkey": s.get("public_key_b64", ""),
            "sender_pubkey_hex": s.get("public_key_hex", ""),
        }
        self._replies_f = (out_dir / "replies.jsonl").open("a", encoding="utf-8")
        self._results_f = (out_dir / "results.jsonl").open("a", encoding="utf-8")
        self.results: list[dict[str, Any]] = []

    # recepción -----------------------------------------------------------
    def on_receive(self, packet: dict[str, Any], interface: Any) -> None:
        decoded = packet.get("decoded", {})
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return
        frm = packet.get("fromId")
        if not frm and isinstance(packet.get("from"), int):
            frm = f"!{packet['from']:08x}"
        heard = "sender" if interface is self.sender else "target"
        r = Reply(time.time(), heard, frm, int(packet.get("channel", 0) or 0),
                  packet.get("id"), decoded.get("text") or "")
        with self.lock:
            self.replies.append(r)
            self.last_rx = r.at
        self._replies_f.write(json.dumps(r.__dict__, ensure_ascii=False) + "\n")
        self._replies_f.flush()
        print(f"      ← [{heard}] {frm} ch{r.channel}: {r.text[:110]!r}")

    # envío ---------------------------------------------------------------
    def _text(self, step: Step, cmd: str) -> tuple[Any, str, set[str]]:
        """-> (interfaz que envía, texto, ids de nodo de los que esperamos respuesta)."""
        t_id, t_short = self.t["node_id"], self.t["short_name"]
        via = step.via
        macs = mac_forms(self.vars.get("mac", "00:00:00:00:00:00"))
        if via == "node":
            return self.sender, f"/nexus-node {t_short} {cmd}", {t_id}
        if via == "node_lower":
            return self.sender, f"/nexus-node {t_short.lower()} {cmd}", {t_id}
        if via == "device":
            return self.sender, f"/nexus-device {t_id} {cmd}", {t_id}
        if via == "mac4":
            return self.sender, f"/nexus-mac {macs['mac4']} {cmd}", {t_id}
        if via == "mac6":
            return self.sender, f"/nexus-mac {macs['mac6']} {cmd}", {t_id}
        if via == "broadcast":
            return self.sender, f"/nexus {cmd}", {t_id}
        if via.startswith("group:"):
            return self.sender, f"/nexus-group {via.split(':', 1)[1]} {cmd}", {t_id}
        if via == "local_target":
            return self.target, f"/nexus-local {cmd}", {t_id}
        if via == "local_sender":
            return self.sender, f"/nexus-local {cmd}", {self.s["node_id"]}
        if via == "raw":
            return self.sender, cmd, {t_id}
        raise ValueError(f"via desconocida: {via}")

    def _send(self, iface: Any, text: str) -> float:
        at = time.time()
        with self.lock:
            self.last_rx = at
        print(f"    → {text}")
        iface.sendText(text, channelIndex=self.channel)
        return at

    def _await(self, sent_at: float, wait: float) -> None:
        quiet = self.args.quiet
        while True:
            time.sleep(0.5)
            now = time.time()
            with self.lock:
                last = self.last_rx
            if now - last >= quiet or now - sent_at >= wait:
                return

    def _run_step(self, step: Step) -> tuple[Status, str, Assembled | None]:
        cmd = step.cmd
        for k, v in self.vars.items():
            cmd = cmd.replace("{" + k + "}", v)
        if "{" in cmd:
            return "INCONCLUSIVE", f"falta variable en {cmd!r} (¿falló una captura previa?)", None
        wait = step.wait or self.args.max_wait
        if step.via in ("burst2_broadcast", "burst2_node"):
            kind = "broadcast" if step.via == "burst2_broadcast" else "node"
            first, _, second = cmd.partition("|")
            second = second or first + " "
            s1 = Step(first, via=kind)
            iface, text, froms = self._text(s1, first)
            t0 = self._send(iface, text)
            time.sleep(1.0)
            self._send(iface, self._text(s1, second)[1])
            self._await(t0, wait)
            with self.lock:
                got = [r for r in self.replies if r.at >= t0 and r.heard_by == "sender"
                       and r.from_id in froms]
            ids = {r.packet_id for r in got}
            v = dict(self.vars, _n=str(len(ids)))
            a = assemble(got)
            assert step.check is not None
            st, note = step.check(a, v)
            return st, note, a
        iface, text, froms = self._text(step, cmd)
        t0 = self._send(iface, text)
        self._await(t0, wait)
        with self.lock:
            got = [r for r in self.replies if r.at >= t0 and r.from_id in froms]
        a = assemble(got) if got else None
        for var, rx in step.capture.items():
            if a:
                m = re.search(rx, a.body, re.S)
                if m:
                    self.vars[var] = m.group(1)
        if step.check is not None and a is not None:
            st, note = step.check(a, dict(self.vars))
            if st in ("PASS", "INFO") and step.expect:
                st2, note2 = evaluate(a, step.expect, step.forbid, step.silence)
                if st2 != "PASS":
                    return st2, note2, a
            return st, note, a
        st, note = evaluate(a, step.expect, step.forbid, step.silence)
        if step.note and st != "PASS":
            note = f"{note} ({step.note})"
        return st, note, a

    # ejecución -----------------------------------------------------------
    def run_test(self, test: Test) -> None:
        print(f"\n[{test.id}] {test.title}  (hipótesis {test.hypo})")
        verdicts: list[dict[str, Any]] = []
        try:
            for step in test.steps:
                st, note, a = self._run_step(step)
                print(f"    = {st}: {note}")
                verdicts.append({"cmd": step.cmd, "via": step.via, "status": st, "note": note,
                                 "marker": a.marker if a else None,
                                 "body": (a.body[:600] if a else None)})
                time.sleep(self.args.gap)
        finally:
            for step in test.restore:  # reversión SIEMPRE, aunque falle algo
                try:
                    st, note, _ = self._run_step(step)
                    print(f"    ↺ restore {step.cmd}: {note}")
                except Exception as exc:  # noqa: BLE001
                    print(f"    ↺ restore FALLÓ {step.cmd}: {exc}")
                time.sleep(self.args.gap)
        order = ["FAIL", "INCONCLUSIVE", "PASS", "INFO"]
        overall = min((v["status"] for v in verdicts), key=lambda s: order.index(s)) if verdicts else "INCONCLUSIVE"
        rec = {"id": test.id, "phase": test.phase, "hypo": test.hypo, "title": test.title,
               "status": overall, "steps": verdicts}
        self.results.append(rec)
        self._results_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._results_f.flush()

    def snapshot(self) -> dict[str, str]:
        """Estado observable que las pruebas mutantes deben dejar igual."""
        snap: dict[str, str] = {}
        for cmd in ("DROPS", "INVALIDS", "ZH LIST", "NIGN", "SECURITY", "SETTINGS", "ROLE"):
            st, _, a = self._run_step(Step(cmd, wait=40))
            snap[cmd] = re.sub(r"\(\d+(/\d+)?\)", "(n)", a.body) if a else "<sin respuesta>"
            time.sleep(self.args.gap)
        return snap


def write_report(r: Runner, s: dict[str, Any], t: dict[str, Any],
                 before: dict[str, str] | None, after: dict[str, str] | None) -> None:
    icon = {"PASS": "✅", "FAIL": "❌", "INCONCLUSIVE": "❔", "INFO": "ℹ️"}
    lines = ["# Validación firmware JenTastic público", "",
             f"- Emisor: {s['short_name']} {s['node_id']} fw `{s.get('firmware')}`",
             f"- Objetivo: {t['short_name']} {t['node_id']} fw `{t.get('firmware')}`",
             f"- Generado: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
             "| Prueba | Hipótesis | Fase | Resultado | Título |", "|---|---|---|---|---|"]
    for x in r.results:
        lines.append(f"| {x['id']} | {x['hypo']} | {x['phase']} | {icon[x['status']]} {x['status']} | {x['title']} |")
    lines.append("")
    for x in r.results:
        lines += [f"## {x['id']} — {x['title']}", ""]
        for v in x["steps"]:
            lines.append(f"- `{v['cmd']}` (via `{v['via']}`) → {icon[v['status']]} {v['note']}"
                         + (f"  marcador {v['marker']}" if v["marker"] else ""))
            if v["body"]:
                lines += ["  ```", "  " + v["body"].replace("\n", "\n  "), "  ```"]
        lines.append("")
    if before is not None and after is not None:
        lines += ["## Estado restaurado", ""]
        for k in before:
            same = before[k] == after.get(k)
            lines.append(f"- `{k}`: {'✅ igual' if same else '❌ DIFIERE'}")
            if not same:
                lines += ["  - antes: `" + before[k][:200].replace("\n", " ") + "`",
                          "  - después: `" + after.get(k, "")[:200].replace("\n", " ") + "`"]
    (r.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def describe(iface: Any) -> dict[str, Any]:
    info = iface.getMyNodeInfo() or {}
    user = info.get("user", {})
    chans = []
    for ch in iface.localNode.channels or []:
        if ch.role != 0:
            chans.append({"index": ch.index, "name": ch.settings.name})
    meta = getattr(iface, "metadata", None)
    pk = user.get("publicKey")  # base64
    pk_hex = base64.b64decode(pk).hex() if pk else ""
    return {"node_id": user.get("id"), "short_name": user.get("shortName"),
            "firmware": getattr(meta, "firmware_version", None) if meta else None,
            "channels": chans, "public_key_b64": pk or "", "public_key_hex": pk_hex}


def trusted_channel(d: dict[str, Any]) -> int | None:
    for ch in d["channels"]:
        if (ch["name"] or "").strip().lower() in TRUSTED_CHANNEL_NAMES:
            return int(ch["index"])
    return None


# ------------------------------------------------------------- self-test --


def self_test() -> int:
    def R(t: str, at: float = 0.0, frm: str = "!aaaaaaaa", heard: str = "sender") -> Reply:
        return Reply(at, heard, frm, 7, None, t)

    # marcador de los 4 estados
    for m in MARKERS:
        a = assemble([R(f"{m} JT VERSION: 2.8.103")])
        assert a.marker == m and a.body == "JT VERSION: 2.8.103", (m, a)
    # páginas sin separador + aviso de paginación aparte
    a = assemble([R("🟢 JT: Paging favorites to mesh...", 0), R("P1: !11111111:AB", 1),
                  R("P2: CD !22222222:EF ", 3)])
    assert a.pages == 2 and a.body == "!11111111:ABCD !22222222:EF " and a.notices, a
    # copia local + malla = una sola
    a = assemble([R("JT VERSION: x", 0, heard="target"), R("JT VERSION: x", 5.4, heard="sender")])
    assert a.messages == 1, a
    # mac: el firmware compara 2 bytes
    assert mac_forms("aa:bb:cc:dd:ee:ff")["mac4"] == "eeff"
    assert mac_forms("aa:bb:cc:dd:ee:ff")["mac6"] == "ddeeff"
    # evaluación
    ok = assemble([R("JT: Unknown command 'INVALIDS NULL ON'")])
    assert evaluate(ok, (r"Unknown command",), (), False)[0] == "PASS"
    assert evaluate(None, (), (), True)[0] == "PASS"
    assert evaluate(None, (r"x",), (), False)[0] == "INCONCLUSIVE"
    assert evaluate(ok, (), (), True)[0] == "FAIL"
    # truncado
    rows = "".join(f"!{i:08x}:N{i % 100:02d} " for i in range(150))
    a = assemble([R("P1: " + rows)])
    assert _truncation_check(a, {"db_nodes": "400"})[0] == "PASS"
    assert _truncation_check(a, {"db_nodes": "150"})[0] == "INCONCLUSIVE"
    # el catálogo de pruebas: ids únicos y fases conocidas
    tests = build_tests()
    ids = [t.id for t in tests]
    assert len(ids) == len(set(ids)), "ids duplicados"
    assert {t.phase for t in tests} <= {"read", "addr", "capture", "mutate", "security"}
    for t in tests:
        for s in t.steps:
            assert s.via.split(":")[0] in {"node", "node_lower", "device", "mac4", "mac6", "broadcast",
                                           "group", "local_target", "local_sender", "raw",
                                           "burst2_broadcast", "burst2_node"}, (t.id, s.via)
    # toda prueba mutante con cambio tiene reversión
    for t in tests:
        if t.phase in ("mutate", "security") and not t.risky:
            assert t.restore, f"{t.id} sin reversión"
    print(f"self-test OK ({len(tests)} pruebas definidas)")
    return 0


# ------------------------------------------------------------------ main --


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--self-test", action="store_true", help="comprueba la lógica sin hardware")
    ap.add_argument("--list", action="store_true", help="lista las pruebas y sale")
    ap.add_argument("--sender", help="puerto del EMISOR")
    ap.add_argument("--target-port", help="puerto del OBJETIVO")
    ap.add_argument("--phases", default="read,addr", help="read,addr,capture,mutate,security")
    ap.add_argument("--only", help="ids o hipótesis separados por coma (R1,H2,…)")
    ap.add_argument("--active-scan", action="store_true", help="incluye NETSCAN/CLIENTSCAN (gastan aire)")
    ap.add_argument("--risky", action="store_true", help="incluye pruebas que podrían reiniciar el nodo")
    ap.add_argument("--quiet", type=float, default=12.0, help="s sin texto nuevo = respondido")
    ap.add_argument("--max-wait", type=float, default=45.0, help="espera máxima por paso")
    ap.add_argument("--gap", type=float, default=10.0, help="s entre pasos (espaciado al mismo destino)")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    tests = build_tests()
    phases = {p.strip() for p in args.phases.split(",") if p.strip()}
    only = {x.strip().upper() for x in args.only.split(",")} if args.only else None
    sel = []
    for t in tests:
        if t.phase not in phases:
            continue
        if only and t.id.upper() not in only and t.hypo.upper() not in only:
            continue
        if t.risky and not (args.risky or (args.active_scan and t.id in ("C16", "C17"))):
            continue
        sel.append(t)
    if args.list:
        for t in sel:
            print(f"{t.id:4} {t.phase:9} {t.hypo:7} {'⚠ ' if t.risky else '  '}{t.title}")
        return 0
    if not sel:
        print("Nada que ejecutar con esos filtros.", file=sys.stderr)
        return 1

    from meshtastic.serial_interface import SerialInterface  # import tardío: --self-test sin librería
    from meshtastic.util import findPorts
    from pubsub import pub

    ports = findPorts(True)
    sender_port = args.sender or (ports[0] if ports else None)
    target_port = args.target_port or next((p for p in ports if p != sender_port), None)
    if not sender_port or not target_port:
        print(f"Necesito DOS nodos por USB; detectados: {ports or 'ninguno'}", file=sys.stderr)
        return 2

    out = Path(__file__).parent / "captures" / datetime.now().strftime("validate-%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    print(f"Conectando EMISOR {sender_port} y OBJETIVO {target_port}…")
    try:
        sender = SerialInterface(sender_port)
        target = SerialInterface(target_port)
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo abrir el puerto: {exc}\n¿Hay un gateway.main usándolo? (pgrep -fl gateway.main)",
              file=sys.stderr)
        return 2

    runner: Runner | None = None
    before = after = None
    s_desc = t_desc = {}
    try:
        s_desc, t_desc = describe(sender), describe(target)
        for label, d in (("EMISOR", s_desc), ("OBJETIVO", t_desc)):
            print(f"{label}: {d['short_name']} {d['node_id']} fw={d['firmware']} canales={d['channels']}")
        ch = trusted_channel(s_desc)
        if ch is None:
            print("El EMISOR no tiene canal Nexus/JenT: no se manda nada.", file=sys.stderr)
            return 3
        runner = Runner(sender, target, s_desc, t_desc, ch, out, args)
        pub.subscribe(runner.on_receive, "meshtastic.receive")
        mutating = bool(phases & {"mutate", "security"})
        if mutating:
            print("\n== Estado inicial (para verificar la restauración) ==")
            before = runner.snapshot()
        # R1 captura la MAC y el rol; si no se ejecuta, se obtiene aparte.
        if "mac" not in runner.vars and not any(t.id == "R1" for t in sel):
            runner._run_step(Step("INFO", capture={"mac": r"MAC:\s*([0-9a-fA-F:]{17})"}))
        for t in sel:
            reason = t.guard(before) if (t.guard and before is not None) else None
            if t.guard and before is None:
                reason = "sin foto inicial del estado"
            if reason:
                print(f"\n[{t.id}] OMITIDA: {reason}")
                rec = {"id": t.id, "phase": t.phase, "hypo": t.hypo, "title": t.title,
                       "status": "INCONCLUSIVE",
                       "steps": [{"cmd": "(guarda)", "via": "-", "status": "INCONCLUSIVE",
                                  "note": f"omitida: {reason}", "marker": None, "body": None}]}
                runner.results.append(rec)
                continue
            runner.run_test(t)
        if mutating:
            print("\n== Estado final ==")
            after = runner.snapshot()
    except KeyboardInterrupt:
        print("\nInterrumpido: restaurando…", file=sys.stderr)
    finally:
        # La reversión de cada prueba vive en su propio `finally` (run_test), también
        # ante Ctrl-C; no hay lista global a ciegas que pueda pisar configuración real.
        for iface in (sender, target):
            try:
                iface.close()
            except Exception:  # noqa: BLE001
                pass
    if runner is not None:
        write_report(runner, s_desc, t_desc, before, after)
        counts: dict[str, int] = {}
        for x in runner.results:
            counts[x["status"]] = counts.get(x["status"], 0) + 1
        print(f"\nResumen: {counts}\nInforme en {out}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
