"""Captura de respuestas reales de JenTastic-Nexus (ADR 0027, iteración 1 → parsers).

Herramienta de desarrollo, fuera del backend y del gateway. Abre DOS nodos por
USB a la vez:

- EMISOR: manda los comandos `/nexus ...` como texto por su canal de confianza
  (`Nexus`/`JenT`, detectado por nombre).
- OBJETIVO: el nodo al que van dirigidos (`-device !id`).

Escucha TODO el texto que llega por las DOS interfaces, así se ve a la vez lo
que la malla entrega al emisor (lo que verá MeshSentinel) y lo que el objetivo
entrega a su propia API (la "copia al móvil local" del documento).

Solo manda comandos de CONSULTA por defecto (no cambia nada en los nodos).

Uso (con el gateway nativo que use esos puertos PARADO):

    arch -arm64 .venv/bin/python tools/nexus_capture.py
    arch -arm64 .venv/bin/python tools/nexus_capture.py --sender /dev/cu.usbmodem101 \
        --target-port /dev/cu.usbmodem1101 --commands "STATS" "WATCH STATS"

Salida en tools/captures/<fecha>/: capture.jsonl (cada paquete de texto con
todos sus campos) + report.md (resumen por comando, texto tal cual).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from meshtastic.serial_interface import SerialInterface
from meshtastic.util import findPorts
from pubsub import pub

TRUSTED_CHANNEL_NAMES = ("nexus", "jent")

# Solo lectura. Orden pensado para salir primero lo pequeño (confirma que el
# canal y la autorización funcionan) y después lo que se espera paginado.
DEFAULT_COMMANDS = (
    "VERSION",
    "INFO",
    "SECURITY",
    "STATS",
    "CONFIG",
    "FIREWALLSTATS",
    "WATCH STATS",
    "LORA",
    "DROPS",
    "NODES",
)


def now() -> float:
    return time.time()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Capture:
    out_dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_rx: float = 0.0
    current: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl = (self.out_dir / "capture.jsonl").open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        with self.lock:
            self.records.append(record)
            self._jsonl.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._jsonl.flush()


def describe_node(iface: SerialInterface) -> dict[str, Any]:
    info = iface.getMyNodeInfo() or {}
    user = info.get("user", {})
    channels = []
    for ch in iface.localNode.channels or []:
        role = ch.role  # 0 DISABLED, 1 PRIMARY, 2 SECONDARY
        if role == 0:
            continue
        channels.append({"index": ch.index, "name": ch.settings.name, "role": role})
    meta = getattr(iface, "metadata", None)
    return {
        "node_id": user.get("id"),
        "node_num": info.get("num"),
        "short_name": user.get("shortName"),
        "long_name": user.get("longName"),
        "hw_model": user.get("hwModel"),
        "firmware": getattr(meta, "firmware_version", None) if meta else None,
        "channels": channels,
    }


def trusted_channel(desc: dict[str, Any]) -> int | None:
    for ch in desc["channels"]:
        if (ch["name"] or "").strip().lower() in TRUSTED_CHANNEL_NAMES:
            return int(ch["index"])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--sender", help="puerto del nodo EMISOR (por defecto el primero)")
    parser.add_argument("--target-port", help="puerto del nodo OBJETIVO (por defecto el otro)")
    parser.add_argument("--commands", nargs="+", default=list(DEFAULT_COMMANDS),
                        help="comandos (sin prefijo) a mandar al objetivo")
    parser.add_argument("--quiet", type=float, default=20.0,
                        help="segundos sin texto nuevo para dar un comando por respondido")
    parser.add_argument("--max-wait", type=float, default=120.0,
                        help="espera máxima por comando")
    parser.add_argument("--literal", action="store_true",
                        help="envía cada comando TAL CUAL (p. ej. \"/nexus IGNORE !id\" para difusión), sin prefijo -node")
    parser.add_argument("--no-extras", action="store_true",
                        help="no mandar las pruebas extra (-local, difusión)")
    args = parser.parse_args()

    ports = findPorts(True)
    sender_port = args.sender or (ports[0] if ports else None)
    target_port = args.target_port or next((p for p in ports if p != sender_port), None)
    if not sender_port or not target_port:
        print(f"Necesito DOS nodos por USB; detectados: {ports or 'ninguno'}", file=sys.stderr)
        return 2

    capture = Capture(Path(__file__).parent / "captures" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    ifaces: dict[int, str] = {}  # id(interface) -> etiqueta

    def on_receive(packet: dict[str, Any], interface: Any) -> None:
        decoded = packet.get("decoded", {})
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return
        ts = now()
        capture.last_rx = ts
        record = {
            "kind": "rx",
            "at": iso(ts),
            "command": capture.current,
            "heard_by": ifaces.get(id(interface), "?"),
            "from": packet.get("fromId") or packet.get("from"),
            "to": packet.get("toId") or packet.get("to"),
            "channel": packet.get("channel", 0),
            "packet_id": packet.get("id"),
            "hop_start": packet.get("hopStart"),
            "hop_limit": packet.get("hopLimit"),
            "rx_snr": packet.get("rxSnr"),
            "rx_rssi": packet.get("rxRssi"),
            "via_mqtt": packet.get("viaMqtt"),
            "text": decoded.get("text"),
        }
        capture.write(record)
        print(f"  ← [{record['heard_by']}] {record['from']} ch{record['channel']}: {record['text']!r}")

    pub.subscribe(on_receive, "meshtastic.receive")

    print(f"Conectando EMISOR {sender_port} y OBJETIVO {target_port}…")
    try:
        sender = SerialInterface(sender_port)
        target = SerialInterface(target_port)
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo abrir el puerto: {exc}\n¿Hay un gateway.main usándolo? "
              "(pgrep -fl gateway.main)", file=sys.stderr)
        return 2

    try:
        s_desc, t_desc = describe_node(sender), describe_node(target)
        ifaces[id(sender)] = f"emisor {s_desc['short_name']}"
        ifaces[id(target)] = f"objetivo {t_desc['short_name']}"
        capture.write({"kind": "nodes", "sender": s_desc, "target": t_desc})
        for label, d in (("EMISOR", s_desc), ("OBJETIVO", t_desc)):
            print(f"{label}: {d['short_name']} / {d['long_name']} {d['node_id']} "
                  f"{d['hw_model']} fw={d['firmware']} canales={d['channels']}")

        channel = trusted_channel(s_desc)
        if channel is None:
            print("El EMISOR no tiene canal 'Nexus'/'JenT': no se manda nada.", file=sys.stderr)
            return 3
        if trusted_channel(t_desc) is None:
            print("AVISO: el OBJETIVO no tiene canal 'Nexus'/'JenT' visible.")
        target_short = t_desc["short_name"]

        # -device !id DESHABILITADO (decisión del usuario, 2026-09-28): no
        # dio respuesta en 20 pruebas de campo consecutivas frente al
        # nombre corto, que sí fue fiable — y el node_id puede regenerarse
        # en cualquier momento desde firmware 2.8, así que ni siquiera es
        # estable como identificador. Todo el direccionamiento dirigido usa
        # -node <shortname>.
        plan = list(args.commands) if args.literal else [f"/nexus-node {target_short} {c}" for c in args.commands]
        if not args.no_extras:
            # Difusión: ¿contesta el objetivo? ¿jitter? ¿contesta el emisor a sí mismo?
            plan.append("/nexus VERSION")
            plan.append("/nexus-local UPTIME")

        for text in plan:
            capture.current = text
            sent_at = now()
            capture.last_rx = sent_at
            capture.write({"kind": "tx", "at": iso(sent_at), "command": text, "channel": channel})
            print(f"\n→ {text}  (canal {channel})")
            sender.sendText(text, channelIndex=channel)
            while True:
                time.sleep(0.5)
                t = now()
                if t - capture.last_rx >= args.quiet or t - sent_at >= args.max_wait:
                    break
            got = sum(1 for r in capture.records if r.get("command") == text and r["kind"] == "rx")
            print(f"   {got} mensaje(s) en {now() - sent_at:.0f} s")
            time.sleep(5)  # cooldown de difusión del firmware (§2.2)
    finally:
        capture.current = None
        for iface in (locals().get("sender"), locals().get("target")):
            if iface is not None:
                iface.close()

    write_report(capture)
    print(f"\nCaptura en {capture.out_dir}")
    return 0


def write_report(capture: Capture) -> None:
    lines = ["# Captura JenTastic-Nexus", ""]
    for rec in capture.records:
        if rec["kind"] == "nodes":
            for role in ("sender", "target"):
                d = rec[role]
                lines.append(f"- **{role}**: {d['short_name']} {d['node_id']} {d['hw_model']} "
                             f"fw `{d['firmware']}` canales `{d['channels']}`")
        elif rec["kind"] == "tx":
            lines += ["", f"## `{rec['command']}`", f"Enviado {rec['at']} por canal {rec['channel']}", ""]
        elif rec["kind"] == "rx":
            lines += [
                f"- {rec['at']} · oído por **{rec['heard_by']}** · de `{rec['from']}` a `{rec['to']}` "
                f"· ch {rec['channel']} · id {rec['packet_id']} · hops {rec['hop_start']}/{rec['hop_limit']}",
                "```", str(rec["text"]), "```",
            ]
    (capture.out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
