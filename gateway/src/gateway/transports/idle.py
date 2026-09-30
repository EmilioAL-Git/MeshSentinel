"""Transporte inactivo (ADR 0021 §8, piscina de repuestos M6.3).

No conecta a ningún nodo ni emite datos de malla: solo late como
"unassigned" hasta que el proceso recibe un command.gateway_connect real
(reclamado desde "+ Añadir gateway"), momento en el que TransportManager lo
sustituye por el transporte de verdad — mismo mecanismo de M5, sin tocarlo.
"""

import asyncio
from typing import Any

from gateway.config import Settings
from gateway.transports.base import EmitFn, Transport


class IdleTransport(Transport):
    name = "idle"

    def __init__(self, emit: EmitFn, settings: Settings | None = None) -> None:
        super().__init__(emit)
        self.status = "unassigned"
        self._closed = asyncio.Event()

    async def run(self) -> None:
        await self.emit_status()
        await self._closed.wait()

    async def send_command(self, command: dict[str, Any]) -> None:
        raise NotImplementedError("idle transport: sin conexión a la malla, nada que ejecutar")

    async def close(self) -> None:
        self._closed.set()
