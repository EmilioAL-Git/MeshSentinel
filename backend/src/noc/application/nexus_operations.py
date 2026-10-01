"""Cola persistente de operaciones JenTastic-Nexus (ADR 0027 §4).

Distinto por diseño del pipeline de administración remota (ADR 0013): el
gateway NUNCA reporta un resultado estructurado de vuelta — el firmware
Nexus solo recibe texto (`sendText`, fire-and-forget) y responde con texto
libre por la malla, igual que cualquier otro nodo hablando por el canal.
Toda la correlación pasa por escuchar `message.received` y reconstruir con
el núcleo puro de `noc.application.nexus` (`CommandPacer` +
`ResponseAssembler` + `ResponseCorrelator` + `parse_response`) — un juego de
estado POR PASARELA mantenido en memoria del proceso, nunca persistido: es
efímero por diseño (igual que los `_waiters` de `GatewayService`/
`NexusGateway`). Una respuesta que llega después de un reinicio del backend
a una operación enviada antes de él se pierde — esa operación queda
"sin respuesta" cuando el vigilante la expire, no hay forma de recuperarla
sin volver a preguntar al nodo.

Vocabulario de operador (M4.1, mismo criterio): Pendiente/Enviado/
Confirmado/Sin respuesta — nunca "succeeded_unconfirmed" ni vocabulario del
pipeline de administración, que es un modelo distinto.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.persistence.nexus_repositories import (
    SqlNexusFlagRepository,
    SqlNexusOperationRepository,
    SqlNexusOperationResponseRepository,
)
from noc.adapters.persistence.settings_repository import SqlSystemSettingsRepository
from noc.application.envelopes import make_command_envelope
from noc.application.nexus.addressing import Broadcast, Device, Group, Local, Mac, ShortName, Target
from noc.application.nexus.builder import NexusCommand, build_command
from noc.application.nexus.correlation import ResponseCorrelator
from noc.application.nexus.interpret import OK, interpret
from noc.application.nexus.pacing import CommandPacer
from noc.application.nexus.parsers import parse_response
from noc.application.nexus.reassembly import AssembledResponse, IncomingText, ResponseAssembler
from noc.application.nexus_settings import merge_settings
from noc.domain.nexus.entities import NexusOperation, NexusOperationResponse

# Destinos de MÚLTIPLES nodos (ADR 0027 §11): una operación así puede
# recibir una respuesta de cada nodo Nexus que la oiga, no una sola — se
# archivan todas en `nexus_operation_responses` en vez de terminar en el
# primer match. Directos (local/node/mac) siguen 1:1, sin cambios.
FANOUT_TARGET_KINDS = frozenset({"broadcast", "group"})

logger = logging.getLogger("noc.nexus.ops")

DEFAULT_RESPONSE_WINDOW_SECONDS = 30.0
SCHEDULER_TICK_SECONDS = 2.0


class NexusTargetError(ValueError):
    pass


def target_from(kind: str, value: str | None) -> Target:
    """Único punto de traducción kind/value (API, BD) → `Target` (núcleo
    puro). `-device` reincorporado como opción consciente (ADR 0027 §13,
    2026-09-29) — el ajuste `addressing_mode` solo controla la
    preselección en la UI, no bloquea nada aquí: quien manda `kind="device"`
    sabe lo que hace."""
    if kind == "broadcast":
        return Broadcast()
    if kind == "local":
        return Local()
    if kind == "node":
        if not value:
            raise NexusTargetError("falta el nombre corto del nodo (-node)")
        return ShortName(value)
    if kind == "device":
        if not value:
            raise NexusTargetError("falta el node_id (-device)")
        return Device(value)
    if kind == "mac":
        if not value:
            raise NexusTargetError("falta la MAC (-mac)")
        return Mac(value)
    if kind == "group":
        if not value:
            raise NexusTargetError("falta el nombre del grupo (-group)")
        return Group(value)
    raise NexusTargetError(f"tipo de destino desconocido: {kind!r}")


@dataclass(slots=True)
class _GatewayState:
    """Estado en memoria de UNA pasarela — nace en el primer envío, nunca
    antes (evita reensamblar tráfico de pasarelas sin ninguna operación
    Nexus activa)."""

    pacer: CommandPacer = field(default_factory=CommandPacer)
    assembler: ResponseAssembler = field(default_factory=ResponseAssembler)
    correlator: ResponseCorrelator = field(default_factory=ResponseCorrelator)


class NexusOperationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        command_queue: RedisCommandQueue,
    ) -> None:
        self._session_factory = session_factory
        self._queue = command_queue
        self._states: dict[str, _GatewayState] = {}
        self._task: asyncio.Task[None] | None = None

    def _state(self, gateway_id: str, response_window_seconds: float = DEFAULT_RESPONSE_WINDOW_SECONDS) -> _GatewayState:
        """Nace con la ventana de correlación (`ResponseCorrelator.window`)
        vigente en ESE momento — un cambio de ajuste posterior no la
        retroactúa en pasarelas ya activas (mismo criterio que el resto del
        estado en memoria de este módulo, efímero por proceso), solo aplica
        a la siguiente pasarela que empiece a despachar."""
        state = self._states.get(gateway_id)
        if state is None:
            state = self._states[gateway_id] = _GatewayState(
                correlator=ResponseCorrelator(window=timedelta(seconds=response_window_seconds))
            )
        return state

    # ── Creación (el router la usa también solo para validar/previsualizar) ──

    async def _load_settings(self) -> dict[str, Any]:
        """Ajustes del módulo (ADR 0027 §13) — leídos de `system_settings` en
        cada llamada, nunca cacheados: es una fila indexada por PK, coste
        marginal, y así un cambio de ajuste se aplica sin reiniciar el
        proceso (mismo criterio que `NexusGateway.is_mode_enabled`)."""
        async with self._session_factory() as session:
            overrides = await SqlSystemSettingsRepository(session).list_all()
        return merge_settings(overrides)

    async def build(
        self, command_name: str, args: list[str], target_kind: str, target_value: str | None
    ) -> NexusCommand:
        """Construye con el núcleo puro sin persistir — `NexusCommandError`/
        `NexusTargetError` si el comando o el destino no son válidos."""
        settings = await self._load_settings()
        target = target_from(target_kind, target_value)
        return build_command(command_name, tuple(args), target=target, prefix=settings["command_prefix"])

    async def create(
        self,
        gateway_id: str,
        command_name: str,
        args: list[str],
        target_kind: str,
        target_value: str | None,
        created_by: str | None,
    ) -> NexusOperation:
        cmd = await self.build(command_name, args, target_kind, target_value)
        op = NexusOperation(
            gateway_id=gateway_id,
            target_kind=target_kind,
            target_value=target_value,
            command_name=cmd.spec.name,
            args=list(cmd.args),
            text=cmd.text,
            destructive=cmd.destructive,
            requires_save=cmd.requires_save,
            busy_seconds=cmd.busy_seconds,
            created_by=created_by,
        )
        async with self._session_factory() as session, session.begin():
            created = await SqlNexusOperationRepository(session).create(op)
        logger.info("nexus.op created id=%s gateway=%s text=%r", created.id, gateway_id, cmd.text)
        return created

    MAX_BATCH_NODES = 300

    async def create_batch(
        self,
        gateway_id: str,
        command_name: str,
        args: list[str],
        node_short_names: list[str],
        interval_seconds: float,
        created_by: str | None,
    ) -> list[NexusOperation]:
        """Lote (ADR 0027 §14): UNA operación `-node <shortname>` por cada
        nodo seleccionado en Flota, compartiendo `batch_key` — el scheduler
        (`_dispatch`) las espacia entre sí por `interval_seconds`, en vez de
        mandarlas todas en el mismo tick (a diferencia de difusión, que ya
        llega a todos de una)."""
        names = [n.strip() for n in node_short_names if n.strip()]
        if not names:
            raise NexusTargetError("selecciona al menos un nodo")
        if len(names) > self.MAX_BATCH_NODES:
            raise NexusTargetError(f"lote demasiado grande (máx. {self.MAX_BATCH_NODES} nodos)")
        if interval_seconds < 1:
            raise NexusTargetError("el intervalo mínimo entre envíos es 1 s")
        settings = await self._load_settings()
        batch_key = uuid4().hex[:16]
        pending_ops: list[NexusOperation] = []
        for name in names:
            cmd = build_command(command_name, tuple(args), target=ShortName(name), prefix=settings["command_prefix"])
            pending_ops.append(
                NexusOperation(
                    gateway_id=gateway_id,
                    target_kind="node",
                    target_value=name,
                    command_name=cmd.spec.name,
                    args=list(cmd.args),
                    text=cmd.text,
                    destructive=cmd.destructive,
                    requires_save=cmd.requires_save,
                    busy_seconds=cmd.busy_seconds,
                    created_by=created_by,
                    batch_key=batch_key,
                    batch_interval_seconds=interval_seconds,
                )
            )
        async with self._session_factory() as session, session.begin():
            repo = SqlNexusOperationRepository(session)
            created = [await repo.create(op) for op in pending_ops]
        logger.info(
            "nexus.op batch created key=%s gateway=%s n=%d command=%s",
            batch_key, gateway_id, len(created), command_name,
        )
        return created

    async def get(self, op_id: int) -> NexusOperation | None:
        async with self._session_factory() as session:
            return await SqlNexusOperationRepository(session).get(op_id)

    async def list_operations(
        self, gateway_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[NexusOperation]:
        async with self._session_factory() as session:
            return await SqlNexusOperationRepository(session).list_operations(gateway_id, status, limit)

    async def list_responses(self, op_id: int) -> list[NexusOperationResponse]:
        """Respuestas individuales de una operación broadcast/group (ADR
        0027 §11) — lista vacía para destinos dirigidos, que nunca escriben
        aquí."""
        async with self._session_factory() as session:
            return await SqlNexusOperationResponseRepository(session).list_for_operation(op_id)

    # ── Scheduler ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="nexus-op-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Nexus operation scheduler tick failed")
            await asyncio.sleep(SCHEDULER_TICK_SECONDS)

    async def tick(self) -> None:
        """Un ciclo: cierra respuestas paginadas por silencio, vigilante de
        sin-respuesta y despacho — extraído para tests (igual que
        `AdminOperationService.tick`)."""
        now = datetime.now(timezone.utc)
        await self._flush_pending_assemblies(now)
        await self._expire_stuck(now)
        await self._dispatch(now)

    async def _dispatch(self, now: datetime) -> None:
        settings = await self._load_settings()
        async with self._session_factory() as session, session.begin():
            repo = SqlNexusOperationRepository(session)
            for op in await repo.list_pending():
                assert op.id is not None
                state = self._state(op.gateway_id, settings["response_window_seconds"])
                target = target_from(op.target_kind, op.target_value)
                cmd = build_command(op.command_name, tuple(op.args), target=target)
                if state.pacer.next_allowed_at(cmd, now) > now:
                    continue  # su turno de espaciado aún no ha llegado
                if op.batch_key and op.batch_interval_seconds and await self._batch_not_ready(
                    repo, op.batch_key, op.batch_interval_seconds, now
                ):
                    continue  # aún no le toca dentro de su lote (ADR 0027 §14)
                envelope = make_command_envelope(
                    "command.send_text",
                    {"text": op.text, "channel_name": settings["channel_name"]},
                    issued_by=op.created_by or "system",
                )
                await self._queue.enqueue(op.gateway_id, envelope)
                state.pacer.record_sent(cmd, now)
                state.correlator.register(str(op.id), target, now, busy_seconds=op.busy_seconds)
                await repo.update_fields(op.id, {"status": "sent", "sent_at": now})
                logger.info("nexus.op sent id=%s gateway=%s text=%r", op.id, op.gateway_id, op.text)

    @staticmethod
    async def _batch_not_ready(
        repo: SqlNexusOperationRepository, batch_key: str, interval_seconds: float, now: datetime
    ) -> bool:
        """Gating de espaciado DENTRO de un lote (ADR 0027 §14) —
        independiente del `CommandPacer`, que no espacia entre destinos
        distintos. `list_pending()` ya ordena por `created_at, id`, así que
        el primer miembro sin hermanos enviados pasa siempre; los
        siguientes esperan a que pase `interval_seconds` desde el último
        envío del MISMO lote."""
        latest = await repo.latest_sent_in_batch(batch_key)
        if latest is None:
            return False
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return now < latest + timedelta(seconds=interval_seconds)

    async def _expire_stuck(self, now: datetime) -> None:
        settings = await self._load_settings()
        async with self._session_factory() as session, session.begin():
            repo = SqlNexusOperationRepository(session)
            responses_repo = SqlNexusOperationResponseRepository(session)
            for op in await repo.list_expired_sent(now, settings["response_window_seconds"]):
                assert op.id is not None
                if op.target_kind in FANOUT_TARGET_KINDS:
                    # Difusión/grupo: la ventana ya se agotó, se cierra con
                    # lo que haya llegado — "confirmado" si respondió al
                    # menos un nodo, "sin respuesta" si ninguno.
                    count = await responses_repo.count_for_operation(op.id)
                    status = "confirmed" if count > 0 else "no_response"
                    await repo.update_fields(op.id, {"status": status, "response_at": now})
                    logger.info("nexus.op %s id=%s gateway=%s responses=%d", status, op.id, op.gateway_id, count)
                else:
                    await repo.update_fields(op.id, {"status": "no_response", "response_at": now})
                    logger.info("nexus.op no_response id=%s gateway=%s", op.id, op.gateway_id)

    async def _flush_pending_assemblies(self, now: datetime) -> None:
        for gateway_id, state in self._states.items():
            for response in state.assembler.flush_expired(now):
                await self._resolve(gateway_id, state, response, now)

    # ── Tracker: mensajes entrantes ──────────────────────────────────────

    async def handle_event(self, event: dict[str, Any], now: datetime | None = None) -> None:
        """`now` inyectable (igual que `_dispatch`/`_expire_stuck`) para tests
        deterministas; en producción siempre el reloj real."""
        if event.get("event_type") != "message.received":
            return
        gateway_id = event.get("gateway_id")
        if not gateway_id or gateway_id not in self._states:
            return  # sin ninguna operación enviada aún en esta pasarela: nada que correlar
        payload = event.get("payload") or {}
        text, from_node_id = payload.get("text"), payload.get("from_node_id")
        if not text or not from_node_id:
            return
        now = now or datetime.now(timezone.utc)
        state = self._states[gateway_id]
        msg = IncomingText(
            from_node_id=from_node_id,
            text=text,
            received_at=now,
            packet_id=payload.get("packet_id"),
        )
        for response in state.assembler.feed(msg):
            await self._resolve(gateway_id, state, response, now)

    async def _resolve(
        self, gateway_id: str, state: _GatewayState, response: AssembledResponse, now: datetime
    ) -> None:
        # El correlator (núcleo puro) NUNCA quita un candidato al hacer
        # match (ver correlation.py): sigue disponible hasta que expira su
        # ventana. Eso es justo lo que necesita difusión/grupo para
        # acumular varias respuestas — aquí solo se decide qué hacer con
        # cada match según el tipo de destino.
        op_id = state.correlator.match(response)
        if op_id is None:
            return  # respuesta sin comando propio que la explique — no es nuestra
        async with self._session_factory() as session, session.begin():
            repo = SqlNexusOperationRepository(session)
            op = await repo.get(int(op_id))
            if op is None or op.status != "sent":
                return  # ya resuelta (vigilante) o desconocida
            parsed = parse_response(op.command_name, response.text, tuple(op.args))
            await self._apply_known_lists(session, op, response, parsed, now)
            if op.target_kind in FANOUT_TARGET_KINDS:
                # Una respuesta MÁS de un nodo, no LA respuesta: se archiva
                # aparte y la operación sigue "sent" (escuchando) hasta que
                # el vigilante cierre la ventana (`_expire_stuck`) — así no
                # se pierde ninguna respuesta posterior por marcar la
                # operación terminal demasiado pronto.
                await SqlNexusOperationResponseRepository(session).add(
                    NexusOperationResponse(
                        operation_id=op.id,  # type: ignore[arg-type]
                        from_node_id=response.from_node_id,
                        received_at=now,
                        response_text=response.text,
                        response_kind=parsed.kind,
                        response_data=parsed.data or None,
                    )
                )
                logger.info(
                    "nexus.op response id=%s gateway=%s from=%s", op_id, gateway_id, response.from_node_id
                )
                return
            await repo.update_fields(
                op.id,  # type: ignore[arg-type]
                {
                    "status": "confirmed",
                    "response_at": now,
                    "response_text": response.text,
                    "response_kind": parsed.kind,
                    "response_data": parsed.data or None,
                },
            )
        # Destino dirigido resuelto: fuera del pool de candidatos, para que
        # una respuesta POSTERIOR de otro comando abierto (p.ej. otro
        # miembro del mismo lote) no se atribuya a este por error de "más
        # reciente" (ver ResponseCorrelator.discard).
        state.correlator.discard(op_id)
        logger.info("nexus.op confirmed id=%s gateway=%s", op_id, gateway_id)

    @staticmethod
    async def _apply_known_lists(
        session: AsyncSession, op: NexusOperation, response: AssembledResponse, parsed: Any, now: datetime
    ) -> None:
        """Alimenta `nexus_node_flags` con lo que acaba de confirmar el nodo
        que respondió: FAV/UNFAV/IGNORE/UNIGNORE añaden o quitan UN sujeto;
        una lectura FAVS/IGNORED (respuesta completa ya reensamblada)
        sustituye la lista entera. Respuestas sin interpretar no tocan nada."""
        repo = SqlNexusFlagRepository(session)
        holder = response.from_node_id
        list_flag = {"FAVS": "favorite", "IGNORED": "ignored", "NIGN LIST": "nign"}.get(parsed.command)
        if list_flag and parsed.kind == "structured":
            entries = [(e["node_id"], e.get("short_name")) for e in parsed.data.get("entries", [])]
            await repo.replace_all(holder, list_flag, entries, now)
            return
        interp = interpret(op.command_name, tuple(op.args), response.text)
        if (
            interp is not None
            and interp.outcome == OK
            and interp.flag_type
            and interp.subject_node_id
            and interp.flag_present is not None
        ):
            await repo.set_present(
                holder, interp.flag_type, interp.subject_node_id, interp.flag_present, now,
                interp.subject_short_name,
            )
