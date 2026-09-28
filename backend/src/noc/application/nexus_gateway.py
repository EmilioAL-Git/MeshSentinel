"""Orquestación impura del módulo JenTastic-Nexus (ADR 0027): envío por el
transporte real/Redis + BD. Capa DELIBERADAMENTE separada de
`noc.application.nexus` (núcleo puro, sin SQL/Redis/FastAPI — verificado por
`test_module_is_pure`); este módulo es quien conecta esas piezas puras
(`build_command`, `parse_response`) con el resto de la aplicación.

Detección de nodos JT (§8 del encargo, D1 del prompt v2.8.006): SOLO
sugiere. `POST /nexus/scan` manda una difusión `/nexus INFO` por el canal
Nexus (autodetectado por el gateway, nunca por índice fijo) y, tras una
ventana de escucha, relee `chat_messages` (ya persistida por el monitor de
Chat — reutilizada en vez de montar una correlación en vivo aparte) filtrando
por lo que el parser puro reconoce como una respuesta INFO estructurada. El
resultado se devuelve como sugerencia; NADA se marca aquí — el operador
acepta cada nodo por separado vía `PUT /nodes/{id}/nexus` (nunca automático,
decisión repetida explícitamente por el usuario en el encargo original).
"""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.persistence.chat_repositories import SqlChatRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.envelopes import make_command_envelope
from noc.application.nexus.addressing import Broadcast
from noc.application.nexus.builder import build_command
from noc.application.nexus.parsers import parse_response
from noc.application.nexus_settings import merge_settings

logger = logging.getLogger("noc.nexus")

# Reutiliza system_settings (migración 0020, clave/valor JSON genérico) —
# sin tabla ni migración propia para el interruptor global.
MODE_SETTING_KEY = "nexus_mode_enabled"

DEFAULT_SCAN_WINDOW_SECONDS = 30.0
# D1 del prompt v2.8.006: "límite de un barrido cada varios minutos". En
# memoria del proceso (un solo backend típico); si se escala a N réplicas
# el límite deja de ser efectivo entre ellas — aceptado, no es una garantía
# de seguridad, solo cortesía de tiempo de aire de la malla.
MIN_SECONDS_BETWEEN_SCANS = 120.0


class NexusScanCooldownError(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"escaneo reciente, reintenta en {retry_after_seconds:.0f}s")


@dataclass(slots=True, frozen=True)
class NexusCandidate:
    node_id: str
    short_name: str | None
    version: str | None
    role: str | None
    marker: str | None  # 🟢/🔴 (firma válida/no válida) — confirmado por el usuario, se muestra tal cual
    already_marked: bool


class NexusGateway:
    """Instancia única (como GatewayService/AdminOperationService): guarda
    el último escaneo por pasarela en memoria para el límite de cadencia."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        command_queue: RedisCommandQueue,
    ) -> None:
        self._session_factory = session_factory
        self._queue = command_queue
        self._last_scan_at: dict[str, datetime] = {}

    # ── Interruptor global ──────────────────────────────────────────────────

    async def is_mode_enabled(self) -> bool:
        async with self._session_factory() as session:
            overrides = await SqlSystemSettingsRepository(session).list_all()
        return bool(overrides.get(MODE_SETTING_KEY, False))

    async def set_mode_enabled(self, value: bool, actor: str | None) -> None:
        async with self._session_factory() as session:
            await SqlSystemSettingsRepository(session).upsert(MODE_SETTING_KEY, bool(value), actor)
            await session.commit()

    # ── Detección (solo sugiere, ver docstring del módulo) ──────────────────

    async def scan(
        self,
        gateway_id: str,
        issued_by: str,
        window_seconds: float = DEFAULT_SCAN_WINDOW_SECONDS,
    ) -> list[NexusCandidate]:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            overrides = await SqlSystemSettingsRepository(session).list_all()
        settings = merge_settings(overrides)
        scan_cooldown = settings["scan_cooldown_seconds"]

        last = self._last_scan_at.get(gateway_id)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < scan_cooldown:
                raise NexusScanCooldownError(scan_cooldown - elapsed)
        self._last_scan_at[gateway_id] = now

        command = build_command("INFO", target=Broadcast(), prefix=settings["command_prefix"])
        envelope = make_command_envelope(
            "command.send_text",
            {"text": command.text, "channel_name": settings["channel_name"]},
            issued_by=issued_by,
        )
        await self._queue.enqueue(gateway_id, envelope)
        logger.info("nexus.scan_started gateway=%s window=%ss", gateway_id, window_seconds)

        await asyncio.sleep(window_seconds)

        # Margen de 2s antes del inicio: la difusión puede tardar en salir
        # del gateway y el reloj de este proceso puede ir ligeramente
        # adelantado respecto al que sella `received_at`.
        since = now - timedelta(seconds=2)
        async with self._session_factory() as session:
            messages = await SqlChatRepository(session).list_messages(
                limit=200, gateway_id=gateway_id, since=since
            )
            candidates_by_node: dict[str, NexusCandidate] = {}
            for msg in messages:
                parsed = parse_response("INFO", msg.text)
                if parsed.kind != "structured":
                    continue
                node_id = parsed.data.get("node_id")
                if not node_id or node_id in candidates_by_node:
                    continue
                candidates_by_node[node_id] = NexusCandidate(
                    node_id=node_id,
                    short_name=parsed.data.get("short_name"),
                    version=parsed.data.get("ver"),
                    role=parsed.data.get("role"),
                    marker=parsed.data.get("marker"),
                    already_marked=False,
                )
            if candidates_by_node:
                existing = await SqlNodeRepository(session).list_for_ids(
                    list(candidates_by_node)
                )
                marked_ids = {n.node_id for n in existing if n.is_nexus}
                candidates_by_node = {
                    node_id: (replace(c, already_marked=True) if node_id in marked_ids else c)
                    for node_id, c in candidates_by_node.items()
                }

        logger.info(
            "nexus.scan_finished gateway=%s candidates=%d", gateway_id, len(candidates_by_node)
        )
        return list(candidates_by_node.values())
