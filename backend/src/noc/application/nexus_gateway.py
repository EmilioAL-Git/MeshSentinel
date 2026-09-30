"""Orquestación impura del módulo JenTastic-Nexus (ADR 0027): envío por el
transporte real/Redis + BD. Capa DELIBERADAMENTE separada de
`noc.application.nexus` (núcleo puro, sin SQL/Redis/FastAPI — verificado por
`test_module_is_pure`); este módulo es quien conecta esas piezas puras
(`build_command`, `parse_response`) con el resto de la aplicación.

Detección de nodos JT (§8 del encargo, D1 del prompt v2.8.006): SOLO
sugiere, por DOS vías independientes que conviven:

1. Activa: `POST /nexus/scan` manda una difusión `/nexus INFO` por el canal
   Nexus (autodetectado por el gateway, nunca por índice fijo) y, tras una
   ventana de escucha, relee `chat_messages` (ya persistida por el monitor
   de Chat — reutilizada en vez de montar una correlación en vivo aparte)
   filtrando por lo que el parser puro reconoce como una respuesta INFO
   estructurada.
2. Pasiva: `handle_event()` está suscrito al mismo bus de eventos que
   `IngestService`/`NexusOperationService` (ver `main.py`) y observa CADA
   `message.received` en vivo, sin enviar nada — cualquier texto con forma
   de respuesta Nexus (`looks_like_nexus_signature`) sugiere a su emisor,
   aunque el backend nunca le haya preguntado nada.

En ambos casos el resultado se devuelve como sugerencia; NADA se marca
aquí — el operador acepta cada nodo por separado vía `PUT /nodes/{id}/nexus`
(nunca automático, decisión repetida explícitamente por el usuario en el
encargo original).
"""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.persistence.chat_repositories import SqlChatRepository
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.envelopes import make_command_envelope
from noc.application.nexus.addressing import Broadcast
from noc.application.nexus.builder import build_command
from noc.application.nexus.parsers import PARSERS, looks_like_nexus_signature, parse_response
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


@dataclass(slots=True, frozen=True)
class PassiveCandidate:
    node_id: str
    gateway_id: str
    sample_text: str
    command: str | None  # nombre PARSERS reconocido en el texto, si lo hay (informativo)
    first_seen_at: datetime
    last_seen_at: datetime
    match_count: int
    already_marked: bool
    short_name: str | None = None  # resuelto contra nodes en list_passive_candidates, nunca al registrar


# Bolsa acotada, en memoria del proceso (mismo criterio que `_last_scan_at`
# y el resto de estado efímero del módulo — nunca persistido): con más de
# esto, se descarta el candidato visto hace más tiempo.
MAX_PASSIVE_CANDIDATES = 200


def _guess_command(text: str) -> str | None:
    """Intenta reconocer el comando exacto probando cada parser conocido —
    solo informativo (se muestra en la sugerencia); si ninguno reconoce el
    formato exacto, el candidato se sigue sugiriendo igual (la firma
    genérica `looks_like_nexus_signature` ya bastó para llegar aquí)."""
    stripped = text.strip()
    for key, parser in PARSERS.items():
        try:
            parser(stripped)
        except Exception:  # noqa: BLE001 — solo probando, cualquier fallo pasa al siguiente
            continue
        return key
    return None


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
        self._passive: dict[str, PassiveCandidate] = {}
        self._passive_dismissed: set[str] = set()

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

    # ── Detección PASIVA (§ nueva, sin enviar nada) ──────────────────────────
    # A diferencia de `scan()` (manda "/nexus INFO" y espera), esta vía nunca
    # transmite: escucha CADA `message.received` que ya pasa por el bus de
    # eventos (igual que `NexusOperationService`/`IngestService`) y sugiere
    # cualquier nodo cuyo texto tenga forma de respuesta Nexus
    # (`looks_like_nexus_signature`), aunque el backend nunca le haya
    # preguntado nada — por ejemplo, si dos nodos JT hablan entre sí, o si un
    # operador humano prueba un comando desde su propio nodo. Sin filtro de
    # canal: igual que `scan()`, el propio texto "JT ..."/"JT: ..." ya es una
    # firma fuerte y el backend no conoce qué `channel_index` es el canal
    # Nexus autodetectado por cada gateway (esa correspondencia vive solo en
    # el propio gateway). SOLO sugiere — nunca escribe `nodes.is_nexus`.

    async def handle_event(self, event: dict[str, Any]) -> None:
        if event.get("event_type") != "message.received":
            return
        payload = event.get("payload") or {}
        text, from_node_id = payload.get("text"), payload.get("from_node_id")
        gateway_id = event.get("gateway_id")
        if not text or not from_node_id or not gateway_id:
            return
        if from_node_id in self._passive_dismissed:
            return
        if not looks_like_nexus_signature(text):
            return  # filtro barato ANTES de tocar BD: la inmensa mayoría del tráfico cae aquí
        if not await self.is_mode_enabled():
            return
        async with self._session_factory() as session:
            overrides = await SqlSystemSettingsRepository(session).list_all()
        if not merge_settings(overrides)["passive_detection_enabled"]:
            return

        now = datetime.now(timezone.utc)
        command = _guess_command(text)
        existing = self._passive.get(from_node_id)
        if existing is not None:
            self._passive[from_node_id] = replace(
                existing,
                gateway_id=gateway_id,
                sample_text=text[:200],
                command=command or existing.command,
                last_seen_at=now,
                match_count=existing.match_count + 1,
            )
            return
        if len(self._passive) >= MAX_PASSIVE_CANDIDATES:
            oldest_id = min(self._passive, key=lambda k: self._passive[k].last_seen_at)
            del self._passive[oldest_id]
        self._passive[from_node_id] = PassiveCandidate(
            node_id=from_node_id,
            gateway_id=gateway_id,
            sample_text=text[:200],
            command=command,
            first_seen_at=now,
            last_seen_at=now,
            match_count=1,
            already_marked=False,
        )
        logger.info("nexus.passive_candidate node=%s gateway=%s command=%s", from_node_id, gateway_id, command)

    async def list_passive_candidates(self) -> list[PassiveCandidate]:
        if not self._passive:
            return []
        async with self._session_factory() as session:
            existing = await SqlNodeRepository(session).list_for_ids(list(self._passive))
        marked_ids = {n.node_id for n in existing if n.is_nexus}
        names = {n.node_id: (n.short_name or n.long_name) for n in existing}
        candidates = [
            replace(c, already_marked=c.node_id in marked_ids, short_name=names.get(c.node_id))
            for c in self._passive.values()
        ]
        candidates.sort(key=lambda c: c.last_seen_at, reverse=True)
        return candidates

    def dismiss_passive_candidate(self, node_id: str) -> None:
        self._passive.pop(node_id, None)
        self._passive_dismissed.add(node_id)
