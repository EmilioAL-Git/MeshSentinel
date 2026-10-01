"""Consola Nexus: el chat del canal Nexus con las respuestas ya interpretadas.

Solo lectura. Reutiliza `chat_messages` (el monitor de Chat ya persiste cada
difusión) filtrado a los canales que cada pasarela conoce por nombre
(`channel_name` de los ajustes Nexus o "nexus"/"jent", igual que el gateway
al enviar) y le superpone la cola de operaciones: cada mensaje recibido
dentro de la ventana de respuesta de un comando enviado se anota con ese
comando y con su interpretación (`nexus.interpret`).

Límite asumido: la correlación por ventana temporal es aproximada para
destinos dirigidos (se comprueba el nombre corto del remitente) y para
difusiones concurrentes (gana el comando más reciente). La verdad
persistente de qué nodo confirmó qué la escribe `NexusOperationService`
(`nexus_node_flags`), con el correlador real — esto es solo la vista.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.chat_repositories import SqlChatRepository
from noc.adapters.persistence.nexus_repositories import SqlNexusFlagRepository, SqlNexusOperationRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository, SqlNodeRepository
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.nexus.interpret import Interpretation, canonical_node_id, interpret
from noc.application.nexus.reassembly import DEFAULT_QUIET, MARKER, PAGE_HEADER, PAGING_TRAILER
from noc.application.nexus_settings import merge_settings
from noc.domain.chat.entities import ChatMessage
from noc.domain.nexus.entities import NexusOperation

DEFAULT_CHANNEL_NAMES = ("nexus", "jent")

def merge_paginated(
    messages: list[ChatMessage], quiet: timedelta = DEFAULT_QUIET
) -> list[tuple[ChatMessage, int]]:
    """Une las páginas `P1:`/`P2:`… de una misma respuesta (mismo nodo y
    pasarela, sin silencios de `quiet`) en UN mensaje, y absorbe el aviso
    final «JT: Paging … to mesh…». Devuelve `(mensaje, nº de trozos)`; 0 =
    mensaje normal. Solo presentación: lo persistido no cambia. Misma regla
    de reensamblado que `ResponseAssembler` (sin separador entre páginas: el
    firmware trocea a ciegas, incluso a mitad de un id)."""
    out: list[list] = []  # [ChatMessage, pages dict | None, last_at, parts]
    open_by_key: dict[tuple[str, str | None], list] = {}
    for m in messages:
        key = (m.from_node_id, m.gateway_id)
        at = _utc(m.received_at)
        text = MARKER.sub("", m.text)
        group = open_by_key.get(key)
        if group is not None and (at is None or at - group[2] >= quiet):
            group = None
            open_by_key.pop(key, None)
        page = PAGE_HEADER.match(text)
        if page is not None:
            number, body = int(page.group(1)), page.group(2)
            if group is not None and number in group[1]:
                group = None  # respuesta nueva que vuelve a empezar
            if group is None:
                group = [m, {}, at, 0]
                out.append(group)
                open_by_key[key] = group
            group[1][number] = body
            group[2] = at
            group[3] += 1
        elif group is not None and PAGING_TRAILER.match(text):
            group[3] += 1  # el aviso de cierre se absorbe
            group[2] = at
            open_by_key.pop(key, None)
        else:
            out.append([m, None, at, 0])
    merged: list[tuple[ChatMessage, int]] = []
    for base, pages, _last, parts in out:
        if pages is None:
            merged.append((base, 0))
        else:
            joined = "".join(pages[n] for n in sorted(pages))
            merged.append((replace(base, text=joined), parts))
    return merged


def _utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _label(node_id: str, names: dict[str, tuple[str | None, str | None]]) -> str:
    short, long_ = names.get(node_id, (None, None))
    name = long_ or short
    return f"{name} ({node_id})" if name else node_id


@dataclass(slots=True)
class ConversationMessage:
    message: ChatMessage
    sender_label: str
    context_op_id: int | None = None
    interpretation: Interpretation | None = None
    subject_label: str | None = None
    parts: int = 0  # >0: respuesta paginada unida a partir de N mensajes


@dataclass(slots=True)
class Conversation:
    messages: list[ConversationMessage] = field(default_factory=list)
    operations: list[NexusOperation] = field(default_factory=list)
    channels: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class KnownFlag:
    flag_type: str
    subject_node_id: str
    subject_label: str
    subject_short_name: str | None
    source: str
    updated_at: datetime | None


class NexusConversationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def conversation(self, gateway_id: str | None, limit: int = 150) -> Conversation:
        async with self._session_factory() as session:
            settings = merge_settings(await SqlSystemSettingsRepository(session).list_all())
            wanted = (
                (settings["channel_name"].strip().lower(),) if settings.get("channel_name") else DEFAULT_CHANNEL_NAMES
            )
            pairs: list[tuple[str, int]] = []
            for gw in await SqlGatewayRepository(session).list_all():
                if gateway_id and gw.gateway_id != gateway_id:
                    continue
                for ch in gw.channels or []:
                    if ch.get("index") is not None and (ch.get("name") or "").strip().lower() in wanted:
                        pairs.append((gw.gateway_id, int(ch["index"])))
            messages = await SqlChatRepository(session).list_for_channels(pairs, limit)
            messages.reverse()  # cronológico (el repositorio devuelve más recientes primero)
            merged = merge_paginated(messages)
            ops = await SqlNexusOperationRepository(session).list_operations(gateway_id, None, 300)
            ops = [o for o in ops if o.created_at is not None]
            ops.reverse()

            # Nombres: remitentes + sujetos de los argumentos de las operaciones.
            ids = {m.from_node_id for m, _ in merged}
            for op in ops:
                if op.args and (sid := canonical_node_id(op.args[0])):
                    ids.add(sid)
            nodes = await SqlNodeRepository(session).list_for_ids(sorted(ids))
            names = {n.node_id: (n.short_name, n.long_name) for n in nodes}

        window = float(settings["response_window_seconds"])
        sent_ops = sorted((o for o in ops if o.sent_at is not None), key=lambda o: _utc(o.sent_at))  # type: ignore[arg-type,return-value]
        out: list[ConversationMessage] = []
        for m, parts in merged:
            cm = ConversationMessage(message=m, sender_label=_label(m.from_node_id, names), parts=parts)
            received = _utc(m.received_at)
            if received is not None:
                op = self._context_op(sent_ops, m, received, window, names)
                if op is not None:
                    subject = canonical_node_id(op.args[0]) if op.args else None
                    cm.context_op_id = op.id
                    cm.subject_label = _label(subject, names) if subject else None
                    cm.interpretation = interpret(
                        op.command_name, tuple(op.args), m.text, subject_label=cm.subject_label, complete=parts > 0
                    )
            out.append(cm)
        return Conversation(messages=out, operations=ops, channels=pairs)

    @staticmethod
    def _context_op(
        sent_ops: list[NexusOperation],
        m: ChatMessage,
        received: datetime,
        window: float,
        names: dict[str, tuple[str | None, str | None]],
    ) -> NexusOperation | None:
        sender_short = (names.get(m.from_node_id, (None, None))[0] or "").lower()
        for op in reversed(sent_ops):  # más reciente primero
            sent = _utc(op.sent_at)
            if sent is None or op.gateway_id != m.gateway_id or received < sent:
                continue
            if received > sent + timedelta(seconds=window + op.busy_seconds):
                continue
            if op.target_kind == "node" and (op.target_value or "").lower() != sender_short:
                continue
            return op
        return None

    async def known_flags(self, node_id: str) -> list[KnownFlag]:
        async with self._session_factory() as session:
            rows = await SqlNexusFlagRepository(session).list_for_node(node_id)
            ids = sorted({r.subject_node_id for r in rows})
            nodes = await SqlNodeRepository(session).list_for_ids(ids)
        names = {n.node_id: (n.short_name, n.long_name) for n in nodes}
        return [
            KnownFlag(
                flag_type=r.flag_type,
                subject_node_id=r.subject_node_id,
                subject_label=_label(r.subject_node_id, names),
                subject_short_name=r.subject_short_name,
                source=r.source,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
