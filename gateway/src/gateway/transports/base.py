"""Interfaz común de transportes hacia el nodo Meshtastic central.

Única frontera del sistema con la librería `meshtastic` (ADR 0002/0006):
las implementaciones emiten exclusivamente eventos normalizados v1 a través
del callback `emit`, nunca estructuras de la librería.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]
"""(event_type, payload) -> None. El transporte no construye el sobre."""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


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
        # Canales del nodo local (índice+nombre), refrescados al conectar —
        # base de los nombres reales de canal en el Registro/Chat.
        self.channels: list[dict[str, Any]] | None = None
        # ¿Puede transmitir a la malla? None = desconocido; False = solo
        # recepción (lora.tx_enabled=false en el firmware, o fuente sin radio
        # como MQTT). ADR 0032.
        self.tx_enabled: bool | None = None
        # Tres señales independientes (no confundir):
        #  · device_response: el nodo conectado RESPONDE por el enlace API
        #    (USB/TCP) — "la pasarela está viva". Es la que decide si se ha caído.
        #  · lora_rx: llegó un paquete de OTRO nodo por radio — hay tráfico.
        #  · lora_tx: la pasarela ordenó una transmisión a la malla.
        # Que no haya tráfico (rx/tx antiguos) NO implica que la pasarela esté caída.
        self.last_device_response_at: datetime | None = None
        self.last_lora_rx_at: datetime | None = None
        self.last_lora_tx_at: datetime | None = None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def mark_device_response(self) -> None:
        self.last_device_response_at = self._now()

    def mark_lora_rx(self) -> None:
        self.last_lora_rx_at = self._now()

    def mark_lora_tx(self) -> None:
        self.last_lora_tx_at = self._now()

    async def probe(self) -> None:
        """Sondeo activo del enlace con el nodo (sin emitir nada a la malla).
        Por defecto no hace nada; los transportes reales piden una respuesta."""

    def virtual_node_info(self) -> dict[str, Any] | None:
        """Estado del nodo virtual (ADR 0033): {port, clients, allow_admin} o
        None si no está activo en este transporte."""
        return None

    async def resync(self) -> bool:
        """Relee el nodo local y republica el snapshot de su NodeDB sin cortar
        el enlace (resincronización manual, ADR 0032). False si esta fuente no
        tiene nada que releer o no está conectada."""
        return False

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
                "channels": self.channels,
                "tx_enabled": self.tx_enabled,
                "virtual_node": self.virtual_node_info(),
                "last_device_response_at": _iso(self.last_device_response_at),
                "last_lora_rx_at": _iso(self.last_lora_rx_at),
                "last_lora_tx_at": _iso(self.last_lora_tx_at),
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
