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
from noc.application.rf_graph import RfEdge, find_asymmetric_links, haversine_m, router_neighbors
from noc.application.node_identity import (
    find_duplicate_keys,
    find_weak_keys,
    pair_identity_changes,
)
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
    # Nodos viejos ya reemplazados por su identidad 2.8 (ADR 0034): no deben
    # disparar node_offline. Lo rellena el engine con TODA la red (antes de
    # escopar por grupo/nodo) — el emparejamiento necesita ver ambos lados.
    superseded_ids: frozenset[str] = frozenset()
    # Paquetes persistidos por nodo en la última hora (reglas de ritmo
    # excesivo). Observado, no exacto: un paquete oído por 2 pasarelas puede
    # contar dos veces — por eso los umbrales por defecto son holgados.
    # Grafo RF dirigido (NeighborInfo + trazas, ADR 0035) y caja envolvente de
    # posiciones de 24 h por nodo (lat_min, lat_max, lon_min, lon_max).
    rf_edges: list[RfEdge] = field(default_factory=list)
    position_bbox_24h: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    position_counts_1h: dict[str, int] = field(default_factory=dict)
    telemetry_counts_1h: dict[str, int] = field(default_factory=dict)
    all_nodes: list = field(default_factory=list)  # list[Node] de toda la red, para key_security
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

    def scoped_to_node(self, node_id: str) -> "NetworkSnapshot":
        """Sub-snapshot con un único nodo (mismo principio que
        `scoped_to_group`, mutuamente excluyente con él): una regla puede
        vigilar un nodo concreto en vez de toda la red o un grupo. Un nodo
        borrado/inexistente = cero coincidencias (misma degradación segura
        que un grupo vacío)."""
        return replace(
            self,
            summaries=[s for s in self.summaries if s.node.node_id == node_id],
            links=[link for link in self.links if link.node_id == node_id],
            neighbors=[n for n in self.neighbors if n.node_id == node_id],
        )


Evaluator = Callable[[AlertRule, NetworkSnapshot], list[AlertCondition]]


def _node_label(s: NodeSummary) -> str:
    return s.node.short_name or s.node.node_id


def _fmt_duration_es(seconds: float) -> str:
    """Segundos en compacto con las dos unidades más significativas:
    "3 d 4 h" / "5 h 12 min" / "12 min". Evita mensajes ilegibles como
    "1334 min" en avisos/mensajes de alerta con duraciones largas."""
    total = max(0, round(seconds))
    if total < 60:
        return f"{total} s"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days > 0:
        return f"{days} d {hours} h" if hours > 0 else f"{days} d"
    if hours > 0:
        return f"{hours} h {mins} min" if mins > 0 else f"{hours} h"
    return f"{mins} min"


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
        if last is None or s.node.node_id in snap.superseded_ids:
            continue
        silent = (snap.now - ensure_utc(last)).total_seconds()
        if silent > duration:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=f"{_node_label(s)} sin actividad desde hace {_fmt_duration_es(silent)}",
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
    """Pasarela caída = el proceso no late, no está conectada o el NODO conectado
    no responde por el enlace API (`last_device_response_at`). El tráfico LoRa
    NO interviene: una malla en silencio no es una pasarela caída."""
    stale_after = rule.duration_seconds if rule.duration_seconds is not None else 90
    out = []
    for g in snap.gateways:
        if (
            g.status == "connected"
            and not is_stale(g.updated_at, stale_after, snap.now)
            and g.last_device_response_at is not None  # pasarelas antiguas sin sello: no se juzga
            and is_stale(g.last_device_response_at, stale_after, snap.now)
        ):
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="gateway",
                    subject_id=g.gateway_id,
                    message=(
                        f"Pasarela {g.gateway_id} sin respuesta del nodo conectado "
                        f"(enlace colgado) desde hace "
                        f"{_fmt_duration_es((snap.now - ensure_utc(g.last_device_response_at)).total_seconds())}"
                    ),
                    correlation_key=f"gateway:{g.gateway_id}",
                )
            )
            continue
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
        if g.last_lora_rx_at is not None:
            rx = ensure_utc(g.last_lora_rx_at)
            heard = rx if heard is None or rx > heard else heard
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
                        f"desde hace {_fmt_duration_es(silent)} (posible radio bloqueada)"
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
                        f"{_fmt_duration_es(age)}"
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
                f"{neighbor} (hace {_fmt_duration_es(age)})"
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


def eval_key_security(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Claves de baja entropía o duplicadas (ADR 0034). Se evalúa sobre TODA la
    red (`all_nodes`) para que un duplicado no desaparezca al escopar por
    grupo, pero solo se alerta de los nodos del snapshot escopado. Los pares
    viejo→nuevo de un cambio de identidad 2.8 NO son duplicados."""
    in_scope = {s.node.node_id: s for s in snap.summaries}
    nodes = snap.all_nodes or [s.node for s in snap.summaries]
    changes = pair_identity_changes(nodes)
    problems: dict[str, list[str]] = {}
    for w in find_weak_keys(nodes):
        problems.setdefault(w.node_id, []).append(f"clave débil ({w.reason})")
    names = {n.node_id: (n.short_name, n.long_name) for n in nodes}
    for g in find_duplicate_keys(nodes, changes):
        same_name = len({names.get(i) for i in g.node_ids}) == 1 and names.get(g.node_ids[0]) != (None, None)
        for node_id in g.node_ids:
            others = [i for i in g.node_ids if i != node_id]
            hint = " (mismo nombre: posible mismo equipo con otro número)" if same_name else ""
            problems.setdefault(node_id, []).append(
                f"clave duplicada con {', '.join(others[:3])}" + (" …" if len(others) > 3 else "") + hint
            )
    out = []
    for node_id, reasons in sorted(problems.items()):
        s = in_scope.get(node_id)
        if s is None:
            continue
        out.append(
            AlertCondition(
                rule_id=rule.id or 0,
                subject_type="node",
                subject_id=node_id,
                message=f"{_node_label(s)}: {'; '.join(reasons)}",
            )
        )
    return out


# ── Informe de problemas de la malla, fase 1 (ADR 0034; niveles A y C, sin grafo) ──
# Umbrales editables en la UI. Los de uso del aire (8 % TX) vienen de la guía
# de buenas prácticas de Meshtastic; los de ritmo son nuestros y se calibran con
# la malla real, no se copian de otros proyectos.
# SIN regla de "desfase de reloj": la única hora que recibimos es la del fix GPS
# (`position_time`), y un nodo sin fix reciente reenvía su última posición con
# hora vieja — no se puede distinguir un reloj roto de un fix antiguo (probado
# con la malla real: 22 falsos positivos, «48 d»).

# Roles retirados del firmware: un nodo que aún los anuncia corre una
# configuración heredada (ROUTER_CLIENT se eliminó; hoy es CLIENT o ROUTER).
OBSOLETE_ROLES = frozenset({"ROUTER_CLIENT"})


def eval_chatty_node(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Nodo parlanchín: `air_util_tx` (observado en su telemetría de
    dispositivo) por encima del umbral — su propio uso del aire, no el canal."""
    threshold = rule.threshold if rule.threshold is not None else 8
    out = []
    for s in snap.summaries:
        tel = s.last_device_telemetry
        if tel and tel.air_util_tx is not None and tel.air_util_tx > threshold:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=(
                        f"{_node_label(s)} transmite demasiado: {tel.air_util_tx:g} % de uso del aire "
                        f"propio (umbral {threshold:g} %)"
                    ),
                )
            )
    return out


def eval_obsolete_role(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    out = []
    for s in snap.summaries:
        role = (s.node.role or "").upper()
        if role in OBSOLETE_ROLES:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=f"{_node_label(s)} anuncia el rol obsoleto {role} (reportado por el nodo)",
                )
            )
    return out


def _eval_rate(rule: AlertRule, snap: NetworkSnapshot, counts: dict[str, int], default: float, what: str):
    threshold = rule.threshold if rule.threshold is not None else default
    labels = {s.node.node_id: _node_label(s) for s in snap.summaries}
    return [
        AlertCondition(
            rule_id=rule.id or 0,
            subject_type="node",
            subject_id=node_id,
            message=f"{labels[node_id]} envía {what} en exceso: {n} en la última hora (umbral {threshold:g}/h)",
        )
        for node_id, n in sorted(counts.items())
        if node_id in labels and n > threshold
    ]


def eval_position_overbroadcast(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    return _eval_rate(rule, snap, snap.position_counts_1h, 12, "posiciones")


def eval_telemetry_overbroadcast(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    return _eval_rate(rule, snap, snap.telemetry_counts_1h, 12, "telemetría")


# ── Informe de problemas, fase 2 (ADR 0035) ─────────────────────────────────

# ROUTER_LATE queda fuera a propósito: está pensado para repetir en clústeres.
ROUTER_ROLES = frozenset({"ROUTER", "REPEATER"})
INFRA_ROLES = frozenset({"ROUTER", "REPEATER", "ROUTER_LATE"})


def eval_asymmetric_link(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Enlace con SNR muy distinto según el sentido (antena/ubicación/ruido
    local desigual). Sujeto = el extremo que oye PEOR; agregado por nodo."""
    threshold = rule.threshold if rule.threshold is not None else 6
    labels = {s.node.node_id: _node_label(s) for s in snap.summaries}
    by_node: dict[str, list[str]] = {}
    for link in find_asymmetric_links(snap.rf_edges, threshold):
        if link.weak_rx not in labels:
            continue
        other = labels.get(link.strong_rx, link.strong_rx)
        by_node.setdefault(link.weak_rx, []).append(
            f"{other} (lo oye a {link.weak_snr:g} dB, él le oye a {link.strong_snr:g} dB)"
        )
    return [
        AlertCondition(
            rule_id=rule.id or 0,
            subject_type="node",
            subject_id=node_id,
            message=f"Enlace asimétrico en {labels[node_id]} (Δ > {threshold:g} dB): {'; '.join(items)}",
        )
        for node_id, items in sorted(by_node.items())
    ]


def eval_router_cluster(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Router enlazado con ≥N routers más: repetición redundante que gasta
    aire sin ganar cobertura. Solo ve los enlaces conocidos (NeighborInfo/trazas)."""
    threshold = int(rule.threshold) if rule.threshold is not None else 3
    routers = {s.node.node_id for s in snap.summaries if (s.node.role or "").upper() in ROUTER_ROLES}
    labels = {s.node.node_id: _node_label(s) for s in snap.summaries}
    adj = router_neighbors(snap.rf_edges, routers)
    return [
        AlertCondition(
            rule_id=rule.id or 0,
            subject_type="node",
            subject_id=node_id,
            message=(
                f"Router {labels[node_id]} enlazado con {len(peers)} routers más "
                f"({', '.join(labels[p] for p in sorted(peers)[:4])}{' …' if len(peers) > 4 else ''}): "
                f"posible repetición redundante"
            ),
        )
        for node_id, peers in sorted(adj.items())
        if len(peers) >= threshold
    ]


def eval_hop_horizon(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Nodo activo en el límite de saltos: más allá no hay margen (el máximo
    de Meshtastic es 7) y cualquier cambio lo deja inalcanzable."""
    threshold = int(rule.threshold) if rule.threshold is not None else 7
    out = []
    for s in snap.summaries:
        hops = s.node.hops_away
        if hops is None or hops < threshold or not s.node.is_online(snap.node_offline_after_seconds, snap.now):
            continue
        out.append(
            AlertCondition(
                rule_id=rule.id or 0,
                subject_type="node",
                subject_id=s.node.node_id,
                message=f"{_node_label(s)} está a {hops} saltos (límite de la malla: 7): sin margen de alcance",
            )
        )
    return out


def eval_router_moving(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    """Router/repetidor cuyas posiciones de 24 h abarcan más de X metros: un
    repetidor fijo que se mueve deja de ser infraestructura fiable (o el GPS
    de baja precisión engaña — por eso el umbral por defecto es holgado)."""
    threshold = rule.threshold if rule.threshold is not None else 1000
    out = []
    for s in snap.summaries:
        if (s.node.role or "").upper() not in INFRA_ROLES:
            continue
        bbox = snap.position_bbox_24h.get(s.node.node_id)
        if bbox is None:
            continue
        spread = haversine_m(bbox[0], bbox[2], bbox[1], bbox[3])
        if spread > threshold:
            out.append(
                AlertCondition(
                    rule_id=rule.id or 0,
                    subject_type="node",
                    subject_id=s.node.node_id,
                    message=(
                        f"{s.node.role} {_node_label(s)} se ha movido {spread / 1000:.1f} km en 24 h "
                        f"(umbral {threshold / 1000:g} km)"
                    ),
                )
            )
    return out


# ── Geofence (zona circular; solo la parte pasiva del disparador por zona) ────
# Alertas basadas en ESTADO: "dentro" dispara al entrar y se resuelve al salir;
# "fuera" dispara al salir de la zona esperada y se resuelve al volver. La
# zona vive en `params` {lat, lon}; el radio en `threshold` (metros). Sin
# siembra por defecto: requiere una zona que solo el operador conoce.

GEOFENCE_MAX_POSITION_AGE_S = 6 * 3600  # una posición más vieja no dice dónde está AHORA


def _geofence(rule: AlertRule, snap: NetworkSnapshot, inside: bool) -> list[AlertCondition]:
    try:
        lat, lon = float(rule.params["lat"]), float(rule.params["lon"])
    except (KeyError, TypeError, ValueError):
        return []  # regla mal formada: nunca dispara, nunca rompe el ciclo
    radius = rule.threshold if rule.threshold else 0
    if radius <= 0:
        return []
    out = []
    for s in snap.summaries:
        pos = s.last_position
        if pos is None or pos.received_at is None or not s.node.is_online(snap.node_offline_after_seconds, snap.now):
            continue
        if (snap.now - ensure_utc(pos.received_at)).total_seconds() > GEOFENCE_MAX_POSITION_AGE_S:
            continue
        dist = haversine_m(lat, lon, pos.latitude, pos.longitude)
        if (dist <= radius) != inside:
            continue
        verb = "dentro de" if inside else "fuera de"
        out.append(
            AlertCondition(
                rule_id=rule.id or 0,
                subject_type="node",
                subject_id=s.node.node_id,
                message=f"{_node_label(s)} {verb} la zona «{rule.name}» ({dist:.0f} m del centro, radio {radius:g} m)",
            )
        )
    return out


def eval_geofence_inside(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    return _geofence(rule, snap, inside=True)


def eval_geofence_outside(rule: AlertRule, snap: NetworkSnapshot) -> list[AlertCondition]:
    return _geofence(rule, snap, inside=False)


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
    "key_security": eval_key_security,
    "chatty_node": eval_chatty_node,
    "obsolete_role": eval_obsolete_role,
    "position_overbroadcast": eval_position_overbroadcast,
    "telemetry_overbroadcast": eval_telemetry_overbroadcast,
    "asymmetric_link": eval_asymmetric_link,
    "router_cluster": eval_router_cluster,
    "hop_horizon": eval_hop_horizon,
    "router_moving": eval_router_moving,
    "geofence_inside": eval_geofence_inside,
    "geofence_outside": eval_geofence_outside,
}

# Tipos cuyo sujeto no son nodos: una regla por grupo no tiene sentido para
# ellos (el escopado filtra nodos/enlaces; low_redundancy SÍ lo admite —
# "redundancia de MI grupo"). La API lo valida contra esta lista.
GROUP_SCOPE_UNSUPPORTED: frozenset[str] = frozenset(
    {"gateway_disconnected", "gateway_no_traffic"}
)
