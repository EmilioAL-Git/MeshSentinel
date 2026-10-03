import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from noc.config import get_settings

logger = logging.getLogger("noc.ws")

router = APIRouter()

# Un send_text que no completa en este plazo indica un cliente colgado
SEND_TIMEOUT_SECONDS = 5.0


class ConnectionHub:
    """Fan-out de eventos del bus hacia los WebSockets conectados."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._dropped_clients = 0

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def dropped_clients(self) -> int:
        return self._dropped_clients

    async def _send(self, ws: WebSocket, data: str) -> None:
        try:
            await asyncio.wait_for(ws.send_text(data), timeout=SEND_TIMEOUT_SECONDS)
        except Exception:
            # Cliente muerto o colgado (pestaña dormida, red a medias): se
            # expulsa en vez de dejar que bloquee al resto
            self._dropped_clients += 1
            await self.unregister(ws)
            with contextlib.suppress(Exception):
                await ws.close()

    async def broadcast(self, event: dict[str, Any]) -> None:
        data = json.dumps(event)
        async with self._lock:
            clients = list(self._clients)
        if clients:
            # Concurrente: un cliente lento ya no retrasa el envío a los demás
            # ni —al ser este handler awaited en serie por el bus— la ingesta
            await asyncio.gather(*(self._send(ws, data) for ws in clients))


hub = ConnectionHub()


@router.websocket("/ws/events")
async def events_ws(ws: WebSocket) -> None:
    settings = get_settings()
    if settings.ws_require_auth:
        auth = ws.app.state.auth
        if await auth.is_protected_mode():
            token = ws.cookies.get(settings.session_cookie_name)
            user = await auth.resolve_session(token) if token else None
            if user is None:
                # Antes de aceptar: el handshake se rechaza (el cliente reintenta
                # con backoff y engancha en cuanto hay sesión)
                await ws.close(code=4401)
                return
    await ws.accept()
    await hub.register(ws)
    try:
        while True:
            # Canal de entrada reservado para suscripciones por tópico (fases futuras)
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        # También ante errores de transporte, no solo desconexión limpia
        await hub.unregister(ws)
