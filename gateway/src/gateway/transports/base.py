"""Interfaz común de transportes hacia el nodo Meshtastic central.

Única frontera del sistema con la librería `meshtastic` (ADR 0002/0006):
las implementaciones emiten exclusivamente eventos normalizados v1 a través
del callback `emit`, nunca estructuras de la librería.
"""

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]
"""(event_type, payload) -> None. El transporte no construye el sobre."""


class Transport(ABC):
    name: str

    def __init__(self, emit: EmitFn) -> None:
        self._emit = emit
        self.status: str = "connecting"
        self.local_node_id: str | None = None
        # Caché no durable del nodo local (M5): refrescada al conectar, expuesta
        # en gateway.status para que la UI la muestre sin persistirla aparte.
        self.local_short_name: str | None = None
        self.local_long_name: str | None = None
        self.local_hw_model: str | None = None
        self.local_firmware_version: str | None = None

    async def emit_status(self, detail: str | None = None) -> None:
        await self._emit(
            "gateway.status",
            {
                "status": self.status,
                "transport": self.name,
                "local_node_id": self.local_node_id,
                "detail": detail,
                "local_short_name": self.local_short_name,
                "local_long_name": self.local_long_name,
                "local_hw_model": self.local_hw_model,
                "local_firmware_version": self.local_firmware_version,
            },
        )

    @abstractmethod
    async def run(self) -> None:
        """Bucle principal: conectar, escuchar y emitir eventos hasta cancelación.

        Debe gestionar su propia reconexión con backoff y emitir
        'gateway.status' en cada cambio de estado.
        """

    @abstractmethod
    async def send_command(self, command: dict[str, Any]) -> None:
        """Ejecuta un comando v1 (command.schema.json) sobre la malla."""

    async def execute_admin(self, operation: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una operación de administración (M1.1: solo GET) y devuelve
        el resultado decodificado. Debe lanzar TimeoutError si el nodo no
        responde y ConnectionError si el transporte no está operativo.

        operation: {operation_id, operation_type, params, timeout_seconds,
        target_node_id}.
        """
        raise NotImplementedError(f"Transport '{self.name}' does not support admin operations")

    @abstractmethod
    async def close(self) -> None: ...
