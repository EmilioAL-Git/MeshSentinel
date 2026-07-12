"""Motor de alertas: reconciliación condiciones ⇄ alertas activas (ADR 0012).

Desacoplado por diseño:
- Entrada: AlertCondition (de evaluadores periódicos hoy; de manejadores de
  eventos en el futuro, vía `reconcile_rule` — misma semántica).
- Salida: AlertTransition entregadas a listeners inyectados (notificador,
  WebSocket, futuros). El motor no conoce Redis, HTTP ni FastAPI.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from noc.adapters.persistence.repositories import SqlGatewayRepository, SqlNodeRepository
from noc.application.alerting.evaluators import EVALUATORS, NetworkSnapshot
from noc.application.dashboard import ensure_utc
from noc.domain.alerts.entities import Alert, AlertCondition, AlertRule

logger = logging.getLogger("noc.alerts")

TransitionKind = Literal["fired", "resolved", "reminder"]


@dataclass(slots=True, frozen=True)
class AlertTransition:
    kind: TransitionKind
    alert: Alert
    # Regla que produjo la transición: permite a los listeners decidir por
    # rule_type (p. ej. la narrativa del diario operativo) sin re-consultarla
    rule: AlertRule | None = None


TransitionListener = Callable[[AlertTransition], Awaitable[None]]


class AlertEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._listeners: list[TransitionListener] = []

    def add_listener(self, listener: TransitionListener) -> None:
        self._listeners.append(listener)

    async def _emit(self, transition: AlertTransition) -> None:
        for listener in self._listeners:
            try:
                await listener(transition)
            except Exception:
                logger.exception("Alert listener failed (kind=%s)", transition.kind)

    # ── Ciclo periódico ──────────────────────────────────────────────────────

    async def evaluate_once(self) -> list[AlertTransition]:
        """Evalúa todas las reglas habilitadas contra el estado actual."""
        async with self._session_factory() as session:
            rules = await SqlAlertRuleRepository(session).list_enabled()
            snapshot = NetworkSnapshot(
                # Los nodos ignorados (M1.2) tampoco generan alertas: sus
                # alertas activas se resuelven solas al desaparecer del snapshot
                summaries=[
                    x for x in await SqlNodeRepository(session).list_summaries() if not x.node.is_ignored
                ],
                gateways=await SqlGatewayRepository(session).list_all(),
            )

        transitions: list[AlertTransition] = []
        for rule in rules:
            evaluator = EVALUATORS.get(rule.rule_type)
            if evaluator is None:
                logger.warning("No evaluator for rule_type=%s (rule=%s)", rule.rule_type, rule.name)
                continue
            conditions = evaluator(rule, snapshot)
            transitions.extend(await self.reconcile_rule(rule, conditions, snapshot.now))

        for t in transitions:
            await self._emit(t)
        return transitions

    # ── Reconciliación (reutilizable por fuentes dirigidas por eventos) ──────

    async def reconcile_rule(
        self, rule: AlertRule, conditions: list[AlertCondition], now: datetime | None = None
    ) -> list[AlertTransition]:
        """Sincroniza las alertas activas de una regla con sus condiciones.

        - condición sin alerta activa -> se crea (fired)
        - alerta activa sin condición -> se resuelve (resolved)
        - alerta activa con condición -> se mantiene; recordatorio si hay cooldown
        Deduplicación por (rule_id, subject_type, subject_id). Las alertas
        acknowledged se conservan hasta que la condición desaparece.
        """
        now = now or datetime.now(timezone.utc)
        transitions: list[AlertTransition] = []

        async with self._session_factory() as session, session.begin():
            repo = SqlAlertRepository(session)
            active = [a for a in await repo.list_active() if a.rule_id == rule.id]
            active_by_key = {(a.subject_type, a.subject_id): a for a in active}
            condition_keys = set()

            for cond in conditions:
                key = (cond.subject_type, cond.subject_id)
                condition_keys.add(key)
                existing = active_by_key.get(key)
                if existing is None:
                    alert = await repo.create(
                        Alert(
                            rule_id=rule.id or 0,
                            rule_name=rule.name,
                            subject_type=cond.subject_type,
                            subject_id=cond.subject_id,
                            severity=rule.severity,
                            message=cond.message,
                            correlation_key=cond.correlation_key,
                            fired_at=now,
                            last_notified_at=now,
                        )
                    )
                    transitions.append(AlertTransition("fired", alert, rule))
                    logger.info(
                        "alert.fired rule=%s subject=%s severity=%s", rule.name, cond.subject_id, rule.severity
                    )
                elif rule.cooldown_seconds > 0 and existing.last_notified_at is not None:
                    since_notified = (now - ensure_utc(existing.last_notified_at)).total_seconds()
                    if since_notified >= rule.cooldown_seconds and existing.status == "firing":
                        await repo.mark_notified(existing.id or 0, now)
                        transitions.append(AlertTransition("reminder", existing, rule))

            for key, alert in active_by_key.items():
                if key not in condition_keys:
                    resolved = await repo.resolve(alert.id or 0, now)
                    if resolved:
                        transitions.append(AlertTransition("resolved", resolved, rule))
                        logger.info("alert.resolved rule=%s subject=%s", rule.name, alert.subject_id)

        return transitions


class AlertEngineLoop:
    """Tarea periódica que dispara la evaluación (separada del motor para poder
    invocar evaluate_once desde tests o desde futuros triggers por evento)."""

    def __init__(self, engine: AlertEngine, interval_seconds: float) -> None:
        self._engine = engine
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="alert-engine")

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
                await self._engine.evaluate_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Alert evaluation cycle failed")
            await asyncio.sleep(self._interval)
