"""Listado de dispositivos serie USB visibles en el host (ADR 0028 §2).

Reimplementa lo que `gateway/transports/usb.py:discover_devices()` ya hacía
con `meshtastic.util.findPorts()` + `pyserial`, pero usando solo `pyserial`
directamente: el lanzador no es parte de `gateway/` y ADR 0001 reserva la
importación de la librería `meshtastic` a `gateway/transports` y
`gateway/decoder` — acoplarse al paquete `gateway` para reusar 15 líneas no
compensa. Misma forma de salida que `DeviceOut` del backend/gateway.
"""

from __future__ import annotations

from typing import TypedDict

import serial.tools.list_ports as list_ports


class DeviceInfo(TypedDict):
    port: str
    description: str | None
    vid: str | None
    pid: str | None
    serial_number: str | None


def list_usb_devices() -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for p in list_ports.comports():
        description = p.description if p.description and p.description != "n/a" else None
        devices.append(
            {
                "port": p.device,
                "description": description,
                "vid": f"{p.vid:04X}" if p.vid is not None else None,
                "pid": f"{p.pid:04X}" if p.pid is not None else None,
                "serial_number": p.serial_number,
            }
        )
    return devices
