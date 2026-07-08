"""Evaluadores de reglas: (regla, snapshot) -> condiciones activas (ADR 0012).

Funciones puras registradas por rule_type. Añadir un tipo de regla nuevo =
registrar un evaluador; el motor no cambia. Las fuentes dirigidas por eventos
(futuras) producirán las mismas AlertCondition y reutilizarán el motor.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from noc.application.dashboard import ensure_utc, is_stale
from noc.domain.alerts.entities import AlertCondition, AlertRule
from noc.domain.nodes.entities import GatewayInfo, NodeSummary


@dataclass(slots=True)
class NetworkSnapshot:
    """Estado observado sobre el que se evalúan las reglas periódicas."""

    summaries: list[NodeSummary] = field(default_factory=list)
    gateways: list[GatewayInfo] = field(default_factory=list)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Evaluator = Callable[[AlertRule, NetworkSnapshot], list[AlertCondition]]


def _node_label(s: NodeSummary) -> str:
    return s.node.short_name or s.node.node_id


def eval_low_battery(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    threshold = rule.threshold if rule.threshold is not None else 20
    out = []
    for s in snap.summaries:
        tel = s.last_device_telemetry
        if tel and tel.battery_level is not None and tel.battery_level < threshold:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=f"Batería de {_node_label(s)} al {tel.battery_level}% (umbral {threshold:g}%)",
                )
            )
    return out


def eval_node_offline(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    duration = rule.duration_seconds if rule.duration_seconds is not None else 1800
    out = []
    for s in snap.summaries:
        last = s.node.last_seen_at
        if last is None:
            continue
        silent = (snap.now - ensure_utc(last)).total_seconds()
        if silent > duration:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=f"{_node_label(s)} sin actividad desde hace {int(silent // 60)} min",
                )
            )
    return out


def eval_snr_degraded(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    threshold = rule.threshold if rule.threshold is not None else -15
    out = []
    for s in snap.summaries:
        snr = s.node.snr
        if snr is not None and snr < threshold:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=f"SNR de {_node_label(s)} degradado: {snr} dB (umbral {threshold:g} dB)",
                )
            )
    return out


def eval_gateway_disconnected(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    stale_after = rule.duration_seconds if rule.duration_seconds is not None else 90
    out = []
    for g in snap.gateways:
        if g.status != "connected" or is_stale(g.updated_at, stale_after, snap.now):
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="gateway",
                    subject_id=g.gateway_id,
                    message=f"Pasarela {g.gateway_id} no operativa (estado: {g.status})",
                    correlation_key=f"gateway:{g.gateway_id}",
                )
            )
    return out


EVALUATORS: dict[str, Evaluator] = {
    "low_battery": eval_low_battery,
    "node_offline": eval_node_offline,
    "snr_degraded": eval_snr_degraded,
    "gateway_disconnected": eval_gateway_disconnected,
}
