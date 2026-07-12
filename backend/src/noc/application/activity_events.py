"""Actividad 2.0: el registro cronológico completo del tráfico de la red.

`ActivityEvent` es el modelo único de una entrada del Registro. Dos
naturalezas conviven en él, documentadas en
`docs/design/actividad-2.0-registro-por-paquete.md`:

- **Paquetes** (`source="mesh"`): un paquete Meshtastic decodificado = una
  entrada, SIEMPRE — nunca se fusionan ni se sustituyen entre sí (una
  telemetría de dispositivo y otra ambiental del mismo nodo son dos
  entradas independientes). Cada entrada tiene una **cabecera humana**
  (`packet_type`, p. ej. "Telemetría del dispositivo") y, aparte, una
  **capa técnica** opcional (`internal_type`/`rssi`/`snr`/`raw`) pensada
  para un desplegable "Ver paquete" — nunca para la vista principal.
- **Sucesos no derivados de un paquete concreto** (`source` `gateway`/
  `alert`/`admin`): transiciones de pasarela, alertas y operaciones
  administrativas. Siguen su propio vocabulario de frase completa
  (`title`), sin `packet_type` (quedan `None`). Algunos hechos de la
  fuente `mesh` (reinicio detectado, nodo nuevo, cambio de identidad)
  también carecen de `packet_type`: son la interpretación de un paquete,
  no el paquete en sí, y se emiten como entrada ADICIONAL junto a la
  entrada del paquete que los originó — nunca la sustituyen.

Cada renderer traduce datos ya normalizados a lenguaje natural de
operador: nunca aparecen nombres internos (portnums, protobuf, estados
técnicos del pipeline) en `packet_type`/`title`/`description`/`details` —
esos solo viven en `internal_type`/`raw`. El frontend solo pinta este
modelo, sin interpretar nada de Meshtastic.

Fuentes (`source`): mesh (paquetes), gateway (conexión de pasarelas),
alert (transiciones del motor de alertas, sin duplicar su lógica), admin
(operaciones y lotes) y system (reservada, sin productor todavía).

Todas las funciones son puras: reciben datos ya cargados (incluida la
etiqueta del nodo, resuelta por el llamante) y devuelven `ActivityEvent`
o `None` cuando la entrada no debe emitirse (p. ej. una alerta sin
redacción de diario definida).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Source = Literal["mesh", "gateway", "alert", "admin", "system"]
Priority = Literal["info", "important", "warning", "critical"]

# Radio medio terrestre: aproximación del radio de incertidumbre de una
# posición Meshtastic a partir de precision_bits (más bits = más precisión).
_EARTH_CIRCUMFERENCE_M = 40_075_017


@dataclass(slots=True)
class ActivityEvent:
    """Una entrada del Registro (§ módulo). `title` es la frase/cabecera que
    ve el operador en la vista principal — para paquetes, es igual a
    `packet_type` (nunca el nombre del portnum); para sucesos no derivados
    de un paquete concreto, es la frase completa de siempre. `node_label`
    se conserva aparte solo para enlazar (chip, Inspector), nunca para
    reconstruir el texto."""

    source: Source
    severity: Priority
    icon: str
    title: str
    node_id: str | None = None
    node_label: str | None = None
    description: str | None = None
    details: list[tuple[str, str]] = field(default_factory=list)
    gateway_id: str | None = None
    batch_id: int | None = None
    timestamp: str = ""
    # Capa humana de cabecera (solo entradas de paquete, `source="mesh"`):
    # "Telemetría del dispositivo", "Posición actualizada"... `None` para
    # sucesos no derivados de un paquete concreto (gateway/alert/admin) y
    # para los hechos adicionales (reinicio, nodo nuevo, identidad).
    packet_type: str | None = None
    # Capa técnica (desplegable "Ver paquete" en el frontend, NUNCA en la
    # cabecera): nombre real del portnum, radio del paquete y el payload de
    # dominio ya normalizado (JSON, no el paquete crudo de la librería).
    internal_type: str | None = None
    rssi: int | None = None
    snr: float | None = None
    raw: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        # tuple -> list para JSON estable
        payload["details"] = [list(pair) for pair in self.details]
        return payload


# ── Formato de valores (siempre legibles, nunca crudos) ─────────────────────


def format_uptime(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    hours, rem_min = seconds // 3600, (seconds % 3600) // 60
    if hours < 48:
        return f"{hours} h {rem_min} min" if rem_min else f"{hours} h"
    return f"{hours // 24} días {hours % 24} h"


def _fmt_battery(level: int) -> str:
    # 101 = alimentación externa (principio de dominio, CLAUDE.md)
    return "alimentación externa" if level >= 101 else f"{level} %"


def _precision_meters(precision_bits: int) -> float:
    """Aproximación del radio de incertidumbre: circunferencia terrestre
    dividida por 2^(bits+1) — más bits truncados por el firmware, radio
    mayor. Bits fuera de [0, 32] se recortan (protocolo no los produce)."""
    bits = max(0, min(32, precision_bits))
    return _EARTH_CIRCUMFERENCE_M / (2 ** (bits + 1))


def _append(details: list[tuple[str, str]], label: str, value: Any, fmt: str = "{}") -> None:
    if value is not None:
        details.append((label, fmt.format(value)))


# ── mesh: un paquete decodificado = una entrada ─────────────────────────────


def render_device_telemetry(
    node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent:
    details: list[tuple[str, str]] = []
    if p.get("battery_level") is not None:
        details.append(("Batería", _fmt_battery(p["battery_level"])))
    _append(details, "Voltaje", p.get("voltage"), "{:.2f} V")
    if p.get("uptime_seconds") is not None:
        details.append(("Tiempo encendido", format_uptime(p["uptime_seconds"])))
    _append(details, "Canal utilizado", p.get("channel_utilization"), "{:.0f} %")
    _append(details, "Air Util TX", p.get("air_util_tx"), "{:.1f} %")
    _append(details, "Canal", p.get("channel_index"))
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="🔋",
        title="Telemetría del dispositivo",
        packet_type="Telemetría del dispositivo",
        internal_type="TELEMETRY_APP (deviceMetrics)",
        node_id=node_id,
        node_label=label,
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_environment_telemetry(
    node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent:
    details: list[tuple[str, str]] = []
    _append(details, "Temperatura", p.get("temperature_c"), "{:.1f} °C")
    _append(details, "Humedad", p.get("relative_humidity"), "{:.0f} %")
    _append(details, "Presión", p.get("barometric_pressure_hpa"), "{:.0f} hPa")
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="🌡",
        title="Telemetría ambiental",
        packet_type="Telemetría ambiental",
        internal_type="TELEMETRY_APP (environmentMetrics)",
        node_id=node_id,
        node_label=label,
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_power_telemetry(
    node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent:
    details: list[tuple[str, str]] = []
    _append(details, "Voltaje", p.get("voltage"), "{:.2f} V")
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="⚡",
        title="Telemetría de energía",
        packet_type="Telemetría de energía",
        internal_type="TELEMETRY_APP (powerMetrics)",
        node_id=node_id,
        node_label=label,
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


_TELEMETRY_RENDERERS = {
    "device": render_device_telemetry,
    "environment": render_environment_telemetry,
    "power": render_power_telemetry,
}


def render_telemetry_packet(
    kind: str, node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent | None:
    """Un paquete de telemetría = una entrada, SIEMPRE con solo sus propios
    campos — nunca se fusiona con el último estado de otros `kind`."""
    renderer = _TELEMETRY_RENDERERS.get(kind)
    return renderer(node_id, label, p, gateway_id) if renderer else None


def render_reboot(
    node_id: str, label: str, uptime_seconds: int, gateway_id: str | None
) -> ActivityEvent:
    """Hecho adicional (no un paquete): se emite JUNTO a la entrada de
    telemetría del dispositivo que lo reveló, nunca en su lugar."""
    return ActivityEvent(
        source="mesh",
        severity="critical",
        icon="🔄",
        title=f"{label} se ha reiniciado",
        node_id=node_id,
        node_label=label,
        details=[("Tiempo desde arranque", format_uptime(uptime_seconds))],
        gateway_id=gateway_id,
    )


def render_position(
    node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent:
    details: list[tuple[str, str]] = []
    _append(details, "Latitud", p.get("latitude"), "{:.5f}")
    _append(details, "Longitud", p.get("longitude"), "{:.5f}")
    _append(details, "Altitud", p.get("altitude_m"), "{:.0f} m")
    _append(details, "Satélites", p.get("sats_in_view"))
    if p.get("precision_bits") is not None:
        meters = _precision_meters(p["precision_bits"])
        details.append(("Precisión", "< 1 m" if meters < 1 else f"{meters:.0f} m"))
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="📍",
        title="Posición actualizada",
        packet_type="Posición actualizada",
        internal_type="POSITION_APP",
        node_id=node_id,
        node_label=label,
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_message(
    node_id: str, label: str, p: dict[str, Any], to_label: str | None, gateway_id: str | None
) -> ActivityEvent:
    # Nombres reales de canal: fase posterior (lectura de localNode.channels)
    channel_index = p.get("channel_index", 0)
    details = [("Destinatario", to_label)] if to_label else [("Canal", f"Canal {channel_index}")]
    return ActivityEvent(
        source="mesh",
        severity="important",
        icon="💬",
        title="Mensaje recibido",
        packet_type="Mensaje recibido",
        internal_type="TEXT_MESSAGE_APP",
        node_id=node_id,
        node_label=label,
        description=f"«{p.get('text', '')}»",
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_node_info(
    node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent:
    """NodeInfo = una entrada SIEMPRE, haya o no novedad (el nodo nuevo o el
    cambio de identidad se narran aparte, como hecho adicional)."""
    details: list[tuple[str, str]] = []
    _append(details, "Nombre", p.get("long_name"))
    _append(details, "Alias", p.get("short_name"))
    _append(details, "Rol", p.get("role"))
    _append(details, "Modelo", p.get("hw_model"))
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="👤",
        title="Información del nodo",
        packet_type="Información del nodo",
        internal_type="NODEINFO_APP",
        node_id=node_id,
        node_label=label,
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_new_node(
    node_id: str, label: str, hw_model: str | None, firmware: str | None, gateway_id: str | None
) -> ActivityEvent:
    """Hecho adicional: se emite JUNTO a la entrada "Información del nodo"."""
    details: list[tuple[str, str]] = []
    _append(details, "Modelo", hw_model)
    _append(details, "Firmware", firmware)
    return ActivityEvent(
        source="mesh",
        severity="important",
        icon="✨",
        title=f"{label} ha aparecido en la red por primera vez",
        node_id=node_id,
        node_label=label,
        details=details,
        gateway_id=gateway_id,
    )


def render_identity_changed(
    node_id: str, old_label: str, new_label: str, gateway_id: str | None
) -> ActivityEvent:
    """Hecho adicional: se emite JUNTO a la entrada "Información del nodo"."""
    return ActivityEvent(
        source="mesh",
        severity="important",
        icon="👤",
        title=f"{old_label} ahora se identifica como «{new_label}»",
        node_id=node_id,
        node_label=new_label,
        details=[("Nombre anterior", old_label), ("Nombre nuevo", new_label)],
        gateway_id=gateway_id,
    )


def render_neighbor_info(
    node_id: str,
    label: str,
    neighbor_labels: list[tuple[str, float | None]],
    gateway_id: str | None,
    p: dict[str, Any],
) -> ActivityEvent:
    details = [
        (n_label, f"{snr:.0f} dB" if snr is not None else "sin dato")
        for n_label, snr in neighbor_labels
    ]
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="🛰",
        title="Información de vecinos",
        packet_type="Información de vecinos",
        internal_type="NEIGHBORINFO_APP",
        node_id=node_id,
        node_label=label,
        description=f"{len(neighbor_labels)} vecinos detectados",
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_traceroute(
    node_id: str, label: str, route_labels: list[str], gateway_id: str | None, p: dict[str, Any]
) -> ActivityEvent:
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="🧭",
        title="Traceroute",
        packet_type="Traceroute",
        internal_type="TRACEROUTE_APP",
        node_id=node_id,
        node_label=label,
        description=" → ".join(route_labels),
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


def render_waypoint(
    node_id: str, label: str, p: dict[str, Any], gateway_id: str | None
) -> ActivityEvent:
    details: list[tuple[str, str]] = []
    _append(details, "Nombre", p.get("name"))
    _append(details, "Latitud", p.get("latitude"), "{:.5f}")
    _append(details, "Longitud", p.get("longitude"), "{:.5f}")
    return ActivityEvent(
        source="mesh",
        severity="info",
        icon="📌",
        title="Waypoint compartido",
        packet_type="Waypoint compartido",
        internal_type="WAYPOINT_APP",
        node_id=node_id,
        node_label=label,
        description=p.get("description"),
        details=details,
        gateway_id=gateway_id,
        rssi=p.get("rssi"),
        snr=p.get("snr"),
        raw=p,
    )


# ── gateway: conexión de pasarelas (inmediato, sin esperar a la alerta) ─────

_GATEWAY_NARRATIVE: dict[str, tuple[Priority, str, str]] = {
    "connected": ("info", "🟢", "Gateway {name} conectado"),
    "disconnected": ("critical", "🔴", "Gateway {name} desconectado"),
    "error": ("critical", "🔴", "Gateway {name} con error de conexión"),
}


def render_gateway_status(
    gateway_id: str,
    name: str | None,
    status: str,
    transport: str | None,
    detail: str | None,
) -> ActivityEvent | None:
    """Solo se narran los estados con significado operativo; connecting /
    reconnecting / unassigned son ruido de ciclo de vida (el estado final
    llegará enseguida como connected o error)."""
    narrative = _GATEWAY_NARRATIVE.get(status)
    if narrative is None:
        return None
    severity, icon, template = narrative
    details: list[tuple[str, str]] = []
    _append(details, "Transporte", transport)
    _append(details, "Detalle", detail)
    return ActivityEvent(
        source="gateway",
        severity=severity,
        icon=icon,
        title=template.format(name=name or gateway_id),
        details=details,
        gateway_id=gateway_id,
    )


# ── alert: transiciones del motor de alertas (la lógica vive SOLO allí) ─────

# rule_type -> (fired, resolved); None = esa transición no se narra.
# gateway_disconnected NO está aquí a propósito: el diario ya lo narra al
# instante desde gateway.status; narrar también la alerta lo duplicaría.
_ALERT_NARRATIVE: dict[str, dict[str, tuple[Priority, str, str]]] = {
    "node_offline": {
        "fired": ("critical", "🔴", "{label} ha desaparecido de la red"),
        "resolved": ("critical", "🟢", "{label} ha reaparecido en la red"),
    },
    "low_battery": {
        "fired": ("warning", "🪫", "La batería de {label} está baja"),
        "resolved": ("info", "🔋", "La batería de {label} se ha recuperado"),
    },
    "snr_degraded": {
        "fired": ("warning", "📶", "El enlace con {label} se ha degradado"),
        "resolved": ("info", "📶", "El enlace con {label} se ha recuperado"),
    },
}


def render_alert_transition(
    rule_type: str,
    kind: str,
    subject_type: str,
    subject_id: str,
    label: str,
    message: str | None,
) -> ActivityEvent | None:
    narrative = _ALERT_NARRATIVE.get(rule_type, {}).get(kind)
    if narrative is None:
        return None
    severity, icon, template = narrative
    return ActivityEvent(
        source="alert",
        severity=severity,
        icon=icon,
        title=template.format(label=label),
        node_id=subject_id if subject_type == "node" else None,
        node_label=label if subject_type == "node" else None,
        description=message,
    )


# ── admin: operaciones y lotes en vocabulario de operador ───────────────────

# operation_type -> (qué se está haciendo, éxito, fracaso). El "qué" se usa
# para created/reintentos ("Iniciando…", "Reintentando…").
_OPERATION_PHRASES: dict[str, tuple[str, str, str]] = {
    "config.set": (
        "la configuración de {node}",
        "Configuración aplicada correctamente en {node}",
        "No se pudo aplicar la configuración en {node}",
    ),
    "module_config.set": (
        "la configuración de módulos de {node}",
        "Configuración de módulos aplicada correctamente en {node}",
        "No se pudo aplicar la configuración de módulos en {node}",
    ),
    "owner.set": (
        "el cambio de nombre de {node}",
        "Nombre de {node} actualizado correctamente",
        "No se pudo actualizar el nombre de {node}",
    ),
    "position.set_fixed": (
        "la posición fija de {node}",
        "Posición fija de {node} establecida correctamente",
        "No se pudo establecer la posición fija de {node}",
    ),
    "favorite.set": (
        "el alta de favorito en {node}",
        "Favorito añadido en {node}",
        "No se pudo añadir el favorito en {node}",
    ),
    "favorite.remove": (
        "la baja de favorito en {node}",
        "Favorito retirado en {node}",
        "No se pudo retirar el favorito en {node}",
    ),
    "ignored.set": (
        "el alta de ignorado en {node}",
        "Nodo ignorado añadido en {node}",
        "No se pudo añadir el nodo ignorado en {node}",
    ),
    "ignored.remove": (
        "la baja de ignorado en {node}",
        "Nodo ignorado retirado en {node}",
        "No se pudo retirar el nodo ignorado en {node}",
    ),
    "contact.add": (
        "el envío de la ficha del nodo a {node}",
        "Ficha del nodo enviada a {node}",
        "No se pudo enviar la ficha del nodo a {node}",
    ),
    "metadata.get": (
        "la lectura de metadatos de {node}",
        "Lectura de metadatos de {node} completada",
        "No se pudieron leer los metadatos de {node}",
    ),
    "nodeinfo.get": (
        "la lectura de identidad de {node}",
        "Lectura de identidad de {node} completada",
        "No se pudo leer la identidad de {node}",
    ),
    "config.get": (
        "la lectura de configuración de {node}",
        "Lectura de configuración de {node} completada",
        "No se pudo leer la configuración de {node}",
    ),
    "module_config.get": (
        "la lectura de configuración de módulos de {node}",
        "Lectura de configuración de módulos de {node} completada",
        "No se pudo leer la configuración de módulos de {node}",
    ),
}

_GENERIC_PHRASES = (
    "la operación sobre {node}",
    "Operación sobre {node} completada correctamente",
    "No se pudo completar la operación sobre {node}",
)


def _phrases(operation_type: str) -> tuple[str, str, str]:
    return _OPERATION_PHRASES.get(operation_type, _GENERIC_PHRASES)


def render_operation(
    operation_type: str,
    state: str,
    node_id: str,
    label: str,
    gateway_id: str | None,
    batch_id: int | None,
    *,
    final_status: str | None = None,
    verify: str | None = None,
    error: str | None = None,
    attempts: int | None = None,
    max_attempts: int | None = None,
) -> ActivityEvent | None:
    """Narrativa del pipeline admin. dispatched/running no se narran (ruido
    interno); CRÍTICO solo cuando la operación ya fracasó definitivamente —
    un reintento programado es WARNING (situación recuperable)."""
    doing, success, failure = (p.format(node=label) for p in _phrases(operation_type))
    common: dict[str, Any] = {
        "source": "admin",
        "node_id": node_id,
        "node_label": label,
        "gateway_id": gateway_id,
        "batch_id": batch_id,
    }

    if state == "created":
        return ActivityEvent(
            severity="important", icon="▶", title=f"Iniciando {doing}", **common
        )
    if state == "retry_scheduled":
        attempt = f" (intento {attempts} de {max_attempts})" if attempts and max_attempts else ""
        return ActivityEvent(
            severity="warning",
            icon="⏳",
            title=f"Reintentando {doing}{attempt}",
            description=error,
            **common,
        )
    if state == "resend_scheduled":
        return ActivityEvent(
            severity="info", icon="↻", title=f"Reenviando por seguridad {doing}", **common
        )
    if state == "finished":
        if final_status == "succeeded":
            details = [("Verificación", "confirmada")] if verify == "confirmed" else []
            return ActivityEvent(
                severity="info", icon="✅", title=success, details=details, **common
            )
        if final_status == "succeeded_unconfirmed":
            return ActivityEvent(
                severity="info",
                icon="✅",
                title=success,
                details=[("Confirmación del nodo", "no disponible")],
                **common,
            )
        if final_status == "verify_failed":
            return ActivityEvent(
                severity="critical",
                icon="❌",
                title=f"{failure}: el nodo no refleja el cambio",
                **common,
            )
        if final_status == "timeout":
            return ActivityEvent(
                severity="critical",
                icon="❌",
                title=f"{failure}: el nodo no respondió a tiempo",
                **common,
            )
        return ActivityEvent(
            severity="critical", icon="❌", title=failure, description=error, **common
        )
    return None  # dispatched, running: ruido interno, no hechos


_BATCH_NARRATIVE: dict[str, tuple[Priority, str, str]] = {
    "created": ("important", "▶", "Lanzado el lote «{name}» sobre {count} nodos"),
    "paused": ("warning", "⏸", "Lote «{name}» pausado"),
    "resumed": ("info", "▶", "Lote «{name}» reanudado"),
    "cancelled": ("warning", "✕", "Lote «{name}» cancelado"),
    "completed": ("info", "✅", "Lote «{name}» completado correctamente"),
    "completed_with_errors": ("critical", "❌", "Lote «{name}» terminado con errores"),
}


def render_batch(
    batch_id: int | None, name: str, state: str, node_count: int
) -> ActivityEvent | None:
    narrative = _BATCH_NARRATIVE.get(state)
    if narrative is None:
        return None
    severity, icon, template = narrative
    return ActivityEvent(
        source="admin",
        severity=severity,
        icon=icon,
        title=template.format(name=name, count=node_count),
        batch_id=batch_id,
    )
