"""Diagnóstico puntual: ¿responde -device igual que -node? (2026-09-28)

Manda la MISMA consulta (INFO) al T1000 en tres formas desde el X1:
-device !id, -node <shortname>, difusión. Escucha por las dos interfaces.
"""
import time
from datetime import datetime, timezone

from meshtastic.serial_interface import SerialInterface
from pubsub import pub

SENDER_PORT = "/dev/cu.usbmodem101"
TARGET_PORT = "/dev/cu.usbmodem1101"

records = []


def on_receive(packet, interface):
    decoded = packet.get("decoded", {})
    if decoded.get("portnum") != "TEXT_MESSAGE_APP":
        return
    label = "sender" if interface is sender else "target"
    records.append((datetime.now(timezone.utc), label, packet.get("fromId"), decoded.get("text")))
    print(f"  <- [{label}] {packet.get('fromId')}: {decoded.get('text')!r}")


pub.subscribe(on_receive, "meshtastic.receive")

print("Conectando...")
sender = SerialInterface(SENDER_PORT)
target = SerialInterface(TARGET_PORT)
try:
    t_info = target.getMyNodeInfo()["user"]
    target_id = t_info["id"]
    target_short = t_info["shortName"]
    print(f"Target: {target_id} short={target_short!r}")

    channel = None
    for ch in sender.localNode.channels or []:
        if ch.role != 0 and (ch.settings.name or "").strip().lower() in ("nexus", "jent"):
            channel = ch.index
            break
    print(f"Canal Nexus: {channel}")

    for label, text in (
        ("DEVICE", f"/nexus-device {target_id} INFO"),
        ("NODE", f"/nexus-node {target_short} INFO"),
        ("BROADCAST", "/nexus INFO"),
    ):
        print(f"\n=== {label}: {text!r} ===")
        sender.sendText(text, channelIndex=channel)
        time.sleep(12)
finally:
    sender.close()
    target.close()

print("\n\nResumen:")
for at, label, frm, text in records:
    print(at.isoformat(), label, frm, repr(text))
