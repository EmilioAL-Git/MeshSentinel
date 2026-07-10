"""Transporte USB/serial (ADR 0009/0010/0023).

Todo el comportamiento (puente PyPubSub->asyncio, reconexión, snapshot,
administración remota) vive en `MeshtasticStreamTransport`; aquí solo la
creación de la SerialInterface, la autodetección de puerto y el escaneo de
dispositivos para el asistente de la UI (M5).
"""

import logging
from typing import Any

from gateway.transports.meshtastic_stream import (
    _FORCE_DISCONNECT as _FORCE_DISCONNECT,  # re-export: usado por tests de ciclo de vida
)
from gateway.transports.meshtastic_stream import MeshtasticStreamTransport

logger = logging.getLogger("gateway.usb")


class MeshtasticUsbTransport(MeshtasticStreamTransport):
    name = "usb"

    @staticmethod
    def discover_devices() -> list[dict[str, Any]]:
        """Escaneo de puertos serie locales (M5): no requiere conexión activa.

        `findPorts` filtra por VID/PID conocidos de Meshtastic; se complementa
        con `serial.tools.list_ports` para descripción/VID/PID/serie, que la
        librería oficial no expone en su resultado (solo la lista de puertos).
        """
        from meshtastic.util import findPorts
        from serial.tools import list_ports

        candidates = set(findPorts(eliminate_duplicates=True))
        devices: list[dict[str, Any]] = []
        for info in list_ports.comports():
            if info.device not in candidates:
                continue
            devices.append(
                {
                    "port": info.device,
                    "description": info.description or None,
                    "vid": f"{info.vid:04x}" if info.vid is not None else None,
                    "pid": f"{info.pid:04x}" if info.pid is not None else None,
                    "serial_number": info.serial_number or None,
                }
            )
        # Puertos detectados por findPorts pero no listados por comports (raro,
        # p. ej. permisos): se incluyen igualmente con datos mínimos.
        known_ports = {d["port"] for d in devices}
        for port in candidates - known_ports:
            devices.append({"port": port, "description": None, "vid": None, "pid": None, "serial_number": None})
        return devices

    def _discover_device(self) -> str | None:
        if self._settings.usb_device:
            logger.info("usb.device_selected device=%s source=config", self._settings.usb_device)
            return self._settings.usb_device
        from meshtastic.util import findPorts

        ports = findPorts(eliminate_duplicates=True)
        logger.info("usb.autodetect candidates=%s", ports)
        if not ports:
            return None
        if len(ports) > 1:
            logger.warning("usb.autodetect multiple devices, using first: %s", ports)
        logger.info("usb.device_selected device=%s source=autodetect", ports[0])
        return ports[0]

    def _connect_blocking(self) -> Any:
        from meshtastic.serial_interface import SerialInterface

        device = self._discover_device()
        if device is None:
            raise ConnectionError("No Meshtastic USB device found (autodetect)")
        return SerialInterface(devPath=device)

    def _endpoint_description(self) -> str:
        device = getattr(self._iface, "devPath", None)
        return str(device or self._settings.usb_device or "autodetect")
