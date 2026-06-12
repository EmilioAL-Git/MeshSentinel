import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("noc.ws")

router = APIRouter()


class ConnectionHub:
    """Fan-out de eventos del bus hacia los WebSockets conectados."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        data = json.dumps(event)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                await self.unregister(ws)


hub = ConnectionHub()


@router.websocket("/ws/events")
async def events_ws(ws: WebSocket) -> None:
    await ws.accept()
    await hub.register(ws)
    try:
        while True:
            # Canal de entrada reservado para suscripciones por tópico (fases futuras)
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.unregister(ws)
