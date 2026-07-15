"""Evaluadores de reglas: (regla, snapshot) -> condiciones activas (ADR 0012).

Funciones puras registradas por rule_type. Añadir un tipo de regla nuevo =
registrar un evaluador; el motor no cambia. Las fuentes dirigidas por eventos
(futuras) producirán las mismas AlertCondition y reutilizarán el motor.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable

from noc.application.dashboard import ensure_utc, is_stale
from noc.application.gateway_stats import compute_multi_gateway_stats
from noc.domain.alerts.entities import AlertCondition, AlertRule
from noc.domain.nodes.entities import GatewayInfo, NodeGatewayLink, NodeNeighbor, NodeSummary


@dataclass(slots=True)
class NetworkSnapshot:
    """Estado observado sobre el que se evalúan las reglas periódicas.

    Ampliado (motor-de-reglas-y-topologia.md §1.2): `links` (N:M
    nodo<->pasarela, M6.1) alimenta gateway_no_traffic/low_redundancy y
    `neighbors` (último enlace por par, node_neighbors) alimenta
    neighbor_link_lost — aditivo, listas vacías si no aplica.
    """

    summaries: list[NodeSummary] = field(default_factory=list)
    gateways: list[GatewayInfo] = field(default_factory=list)
    links: list[NodeGatewayLink] = field(default_factory=list)
    neighbors: list[NodeNeighbor] = field(default_factory=list)
    node_offline_after_seconds: int = 900
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def scoped_to_group(self, group_id: int) -> "NetworkSnapshot":
        """Sub-snapshot con SOLO los nodos miembros del grupo (§1.3 opción A):
        mismo principio que `scope_to_members` de gateway_stats — pre-filtrar
        las entradas, nunca cambiar los evaluadores. `NodeSummary.group_ids`
        ya viene cargado, sin consulta extra. Las pasarelas no se filtran
        (un grupo de nodos no posee pasarelas)."""
        members = {s.node.node_id for s in self.summaries if group_id in s.group_ids}
        return replace(
            self,
            summaries=[s for s in self.summaries if s.node.node_id in members],
            links=[link for link in self.links if link.node_id in members],
            neighbors=[n for n in self.neighbors if n.node_id in members],
        )


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


def eval_gateway_no_traffic(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Pasarela conectada pero SORDA: el heartbeat sigue vivo pero no oye a
    ningún nodo desde hace `duration_seconds` — el caso real detectado en la
    sesión de campo post-hardening (radio muerta con firmware/API vivos, se
    cura con corte de alimentación). Sin ningún enlace previo no hay línea
    base y no se dispara (arranque en frío)."""
    duration = rule.duration_seconds if rule.duration_seconds is not None else 1800
    last_heard: dict[str, datetime] = {}
    for link in snap.links:
        if link.last_heard_at is not None:
            prev = last_heard.get(link.gateway_id)
            if prev is None or ensure_utc(link.last_heard_at) > prev:
                last_heard[link.gateway_id] = ensure_utc(link.last_heard_at)
    out = []
    for g in snap.gateways:
        if g.deleted_at is not None or g.status != "connected":
            continue  # desconectada ya la cubre gateway_disconnected
        heard = last_heard.get(g.gateway_id)
        if heard is None:
            continue
        silent = (snap.now - heard).total_seconds()
        if silent > duration:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="gateway",
                    subject_id=g.gateway_id,
                    message=(
                        f"Pasarela {g.name or g.gateway_id} conectada pero sin tráfico de malla "
                        f"desde hace {int(silent // 60)} min (posible radio bloqueada)"
                    ),
                    correlation_key=f"gateway:{g.gateway_id}",
                )
            )
    return out


def eval_low_redundancy(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """% de nodos oídos por >=2 pasarelas por debajo del umbral. Reutiliza
    `compute_multi_gateway_stats` (M6.2) tal cual — solo tiene sentido con
    2+ pasarelas operativas; con una sola, la redundancia 0 % es la
    condición normal y no se dispara."""
    threshold = rule.threshold if rule.threshold is not None else 50
    operative = [g for g in snap.gateways if g.deleted_at is None and g.enabled]
    if len(operative) < 2:
        return []
    stats = compute_multi_gateway_stats(
        links=snap.links,
        gateways=snap.gateways,
        nodes=[s.node for s in snap.summaries],
        offline_threshold_seconds=snap.node_offline_after_seconds,
        now=snap.now,
    )
    if stats.nodes_observed == 0 or stats.redundancy_percent >= threshold:
        return []
    return [
        AlertCondition(
            rule_id=rule.id or 0,
            subject_type="system",
            subject_id="redundancy",
            message=(
                f"Redundancia de pasarelas al {stats.redundancy_percent:g} % "
                f"({stats.nodes_shared}/{stats.nodes_observed} nodos con doble cobertura, "
                f"umbral {threshold:g} %)"
            ),
            correlation_key="system:redundancy",
        )
    ]


def eval_temperature_high(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Mismo origen de dato que el Dashboard (avg_temperature_c):
    `last_device_telemetry.temperature_c` — criterio único, hardening."""
    threshold = rule.threshold if rule.threshold is not None else 45
    out = []
    for s in snap.summaries:
        tel = s.last_device_telemetry
        if tel and tel.temperature_c is not None and tel.temperature_c > threshold:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=(
                        f"Temperatura de {_node_label(s)}: {tel.temperature_c:g} °C "
                        f"(umbral {threshold:g} °C)"
                    ),
                )
            )
    return out


def eval_channel_utilization_high(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    # 25 % es el límite operativo recomendado por Meshtastic para el canal
    threshold = rule.threshold if rule.threshold is not None else 25
    out = []
    for s in snap.summaries:
        tel = s.last_device_telemetry
        if tel and tel.channel_utilization is not None and tel.channel_utilization > threshold:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=(
                        f"Canal saturado en {_node_label(s)}: {tel.channel_utilization:g} % "
                        f"de utilización (umbral {threshold:g} %)"
                    ),
                )
            )
    return out


def eval_position_lost(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Nodo ONLINE cuyo GPS dejó de reportar: exige posición previa (los
    nodos sin GPS no tienen línea base y nunca disparan) y nodo activo (un
    nodo offline ya lo cubre node_offline, no hace falta duplicar)."""
    duration = rule.duration_seconds if rule.duration_seconds is not None else 7200
    out = []
    for s in snap.summaries:
        pos = s.last_position
        if pos is None or pos.received_at is None:
            continue
        if not s.node.is_online(snap.node_offline_after_seconds, snap.now):
            continue
        age = (snap.now - ensure_utc(pos.received_at)).total_seconds()
        if age > duration:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=(
                        f"{_node_label(s)} activo pero sin posición desde hace "
                        f"{int(age // 60)} min"
                    ),
                )
            )
    return out


def eval_neighbor_link_lost(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Enlace nodo<->nodo visto -> ausente (§1.2, desbloqueada por la ingesta
    de NeighborInfo): agregado POR NODO emisor (una alerta con todos sus
    enlaces perdidos, no una por par — el sujeto sigue siendo un node_id real
    y el Inspector puede abrirlo). El engine acota `neighbors` con una
    ventana de carga: un enlace perdido hace semanas desaparece del snapshot
    y su alerta se auto-resuelve."""
    duration = rule.duration_seconds if rule.duration_seconds is not None else 7200
    label_of = {s.node.node_id: _node_label(s) for s in snap.summaries}
    lost_by_node: dict[str, list[str]] = {}
    for n in snap.neighbors:
        if n.received_at is None:
            continue
        age = (snap.now - ensure_utc(n.received_at)).total_seconds()
        if age > duration:
            neighbor = label_of.get(n.neighbor_id, n.neighbor_id)
            lost_by_node.setdefault(n.node_id, []).append(
                f"{neighbor} (hace {int(age // 3600)} h)"
            )
    out = []
    for node_id, lost in sorted(lost_by_node.items()):
        label = label_of.get(node_id, node_id)
        out.append(
            AlertCondition(
                rule_id=rule.id or 0,
                subject_type="node",
                subject_id=node_id,
                message=f"{label} ha perdido el enlace con: {', '.join(lost)}",
            )
        )
    return out


EVALUATORS: dict[str, Evaluator] = {
    "low_battery": eval_low_battery,
    "node_offline": eval_node_offline,
    "snr_degraded": eval_snr_degraded,
    "gateway_disconnected": eval_gateway_disconnected,
    "gateway_no_traffic": eval_gateway_no_traffic,
    "low_redundancy": eval_low_redundancy,
    "temperature_high": eval_temperature_high,
    "channel_utilization_high": eval_channel_utilization_high,
    "position_lost": eval_position_lost,
    "neighbor_link_lost": eval_neighbor_link_lost,
}

# Tipos cuyo sujeto no son nodos: una regla por grupo no tiene sentido para
# ellos (el escopado filtra nodos/enlaces; low_redundancy SÍ lo admite —
# "redundancia de MI grupo"). La API lo valida contra esta lista.
GROUP_SCOPE_UNSUPPORTED: frozenset[str] = frozenset(
    {"gateway_disconnected", "gateway_no_traffic"}
)
