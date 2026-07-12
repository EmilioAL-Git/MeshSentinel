"""Actividad 2.0: el registro cronológico completo del tráfico de la red.

Dos niveles: renderers puros (vocabulario, cabecera humana vs. capa técnica,
"un paquete = una entrada", cuándo se añaden hechos adicionales) y la
integración con IngestService/ActivityPublisher (telemetría por-paquete,
detección de reinicio como entrada adicional, NodeInfo siempre + hecho
adicional, mensajes, vecinos/traceroute/waypoint) con un recorder adjunto
al singleton, igual que test_activity.py.
"""

import uuid
from datetime import datetime, timezone

from noc.application import activity_events as ae
from noc.application.activity import activity
from noc.application.ingest import IngestService

NODE = "!00000001"


def make_event(event_type: str, payload: dict, gateway_id: str = "gw-test") -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


# ── Renderers puros ──────────────────────────────────────────────────────────


def test_render_device_telemetry_packet():
    p = {
        "battery_level": 94,
        "voltage": 4.08,
        "uptime_seconds": 82800,
        "channel_utilization": 61.0,
        "rssi": -80,
        "snr": 7.5,
    }
    event = ae.render_device_telemetry(NODE, "EA2ABC", p, "gw-test")
    assert event.packet_type == "Telemetría del dispositivo"
    assert event.title == "Telemetría del dispositivo"  # cabecera == title, nunca el portnum
    assert event.internal_type == "TELEMETRY_APP (deviceMetrics)"
    assert event.rssi == -80
    assert event.snr == 7.5
    assert event.raw is p
    labels = dict(event.details)
    assert labels["Batería"] == "94 %"
    assert labels["Voltaje"] == "4.08 V"
    assert labels["Tiempo encendido"] == "23 h"
    assert "Temperatura" not in labels  # nunca se mezcla con environment


def test_render_environment_telemetry_packet_is_independent():
    """Un paquete environment nunca hereda campos de un paquete device."""
    event = ae.render_environment_telemetry(NODE, "EA2ABC", {"temperature_c": 35.4}, None)
    assert event.packet_type == "Telemetría ambiental"
    labels = dict(event.details)
    assert labels["Temperatura"] == "35.4 °C"
    assert "Batería" not in labels


def test_render_telemetry_packet_dispatches_by_kind():
    device = ae.render_telemetry_packet("device", NODE, "EA2ABC", {"battery_level": 50}, None)
    assert device.packet_type == "Telemetría del dispositivo"
    env = ae.render_telemetry_packet("environment", NODE, "EA2ABC", {"temperature_c": 10}, None)
    assert env.packet_type == "Telemetría ambiental"
    power = ae.render_telemetry_packet("power", NODE, "EA2ABC", {"voltage": 12.0}, None)
    assert power.packet_type == "Telemetría de energía"


def test_format_uptime_scales():
    assert ae.format_uptime(12) == "12 s"
    assert ae.format_uptime(300) == "5 min"
    assert ae.format_uptime(23 * 3600 + 600) == "23 h 10 min"
    assert ae.format_uptime(3 * 86400) == "3 días 0 h"


def test_render_position_includes_precision_never_hides_low_bits():
    p = {"latitude": 38.99421, "longitude": -1.85563, "precision_bits": 20, "rssi": -90, "snr": 4.0}
    event = ae.render_position(NODE, "EA2ABC", p, "gw-test")
    assert event.packet_type == "Posición actualizada"
    assert event.internal_type == "POSITION_APP"
    labels = dict(event.details)
    assert labels["Latitud"] == "38.99421"
    assert "Precisión" in labels and labels["Precisión"].endswith(" m")
    assert event.rssi == -90 and event.snr == 4.0


def test_precision_meters_more_bits_means_smaller_radius():
    assert ae._precision_meters(10) > ae._precision_meters(32)


def test_render_message_packet():
    p = {"text": "Hola, ¿qué tal estáis?", "channel_index": 0, "rssi": -95, "snr": 2.0}
    event = ae.render_message(NODE, "EA2ABC", p, None, "gw-test")
    assert event.packet_type == "Mensaje recibido"
    assert event.description == "«Hola, ¿qué tal estáis?»"
    assert ("Canal", "Canal 0") in event.details
    assert event.severity == "important"


def test_render_message_to_direct_node():
    event = ae.render_message(NODE, "EA2ABC", {"text": "hola"}, "EA2XYZ", None)
    assert ("Destinatario", "EA2XYZ") in event.details


def test_render_node_info_always_present_with_technical_layer():
    p = {"long_name": "Pico Almanzor", "short_name": "ALM", "role": "ROUTER", "rssi": -70, "snr": 8.0}
    event = ae.render_node_info(NODE, "ALM", p, "gw-test")
    assert event.packet_type == "Información del nodo"
    assert event.internal_type == "NODEINFO_APP"
    labels = dict(event.details)
    assert labels["Nombre"] == "Pico Almanzor"
    assert labels["Alias"] == "ALM"
    assert labels["Rol"] == "ROUTER"
    # Nunca nombres internos en la cabecera humana
    assert "NODEINFO_APP" not in event.packet_type
    assert "NODEINFO_APP" not in event.title


def test_render_new_node_and_identity_changed_have_no_packet_type():
    """Son hechos adicionales, no paquetes — no llevan cabecera de paquete."""
    new_node = ae.render_new_node(NODE, "EA2ABC", "TBEAM", "2.5", None)
    assert new_node.packet_type is None
    identity = ae.render_identity_changed(NODE, "EA2ABC", "Refugio", None)
    assert identity.packet_type is None
    assert identity.title == "EA2ABC ahora se identifica como «Refugio»"


def test_render_neighbor_info_shows_semantic_snr_in_details_not_technical():
    p = {"rssi": -60, "snr": 5.0}
    event = ae.render_neighbor_info(
        NODE, "EA2ABC", [("EA2DEF", -8.0), ("EA2XYZ", -11.0)], "gw-test", p
    )
    assert event.packet_type == "Información de vecinos"
    assert event.description == "2 vecinos detectados"
    assert ("EA2DEF", "-8 dB") in event.details
    assert ("EA2XYZ", "-11 dB") in event.details
    # El SNR de cada vecino es contenido semántico (vista principal); el
    # SNR/RSSI del propio paquete recibido va en los campos técnicos
    assert event.rssi == -60 and event.snr == 5.0


def test_render_traceroute_route_as_arrows():
    event = ae.render_traceroute(NODE, "EA2ABC", ["EA2ABC", "EA2XYZ", "EA2DEF"], None, {})
    assert event.packet_type == "Traceroute"
    assert event.description == "EA2ABC → EA2XYZ → EA2DEF"


def test_render_waypoint_packet():
    p = {"name": "Refugio Sur", "description": "Punto de encuentro", "latitude": 40.4, "longitude": -3.7}
    event = ae.render_waypoint(NODE, "EA2ABC", p, None)
    assert event.packet_type == "Waypoint compartido"
    assert event.description == "Punto de encuentro"
    assert ("Nombre", "Refugio Sur") in event.details


def test_render_operation_vocabulary_and_priorities():
    kwargs = dict(node_id=NODE, label="EA2ABC", gateway_id="gw-test", batch_id=None)
    created = ae.render_operation("config.set", "created", **kwargs)
    assert created.severity == "important"
    assert created.title == "Iniciando la configuración de EA2ABC"

    retry = ae.render_operation(
        "config.set", "retry_scheduled", attempts=1, max_attempts=3, error="timeout", **kwargs
    )
    assert retry.severity == "warning"  # recuperable: nunca crítico
    assert "Reintentando la configuración de EA2ABC" in retry.title

    ok = ae.render_operation("config.set", "finished", final_status="succeeded", **kwargs)
    assert ok.severity == "info"
    assert ok.title == "Configuración aplicada correctamente en EA2ABC"

    failed = ae.render_operation(
        "config.set", "finished", final_status="failed", error="NAK", **kwargs
    )
    assert failed.severity == "critical"  # solo al fracaso definitivo
    assert failed.title == "No se pudo aplicar la configuración en EA2ABC"

    timeout = ae.render_operation("config.set", "finished", final_status="timeout", **kwargs)
    assert "no respondió a tiempo" in timeout.title

    # dispatched/running: ruido interno del pipeline, no hechos
    assert ae.render_operation("config.set", "dispatched", **kwargs) is None
    assert ae.render_operation("config.set", "running", **kwargs) is None

    # Ningún nombre interno se filtra al operador
    for event in (created, retry, ok, failed, timeout):
        assert "config.set" not in event.title
        assert "FAILED" not in event.title


def test_render_batch_vocabulary():
    created = ae.render_batch(7, "región EU", "created", 12)
    assert created.severity == "important"
    assert created.title == "Lanzado el lote «región EU» sobre 12 nodos"
    errors = ae.render_batch(7, "región EU", "completed_with_errors", 12)
    assert errors.severity == "critical"


def test_render_alert_transitions():
    fired = ae.render_alert_transition("node_offline", "fired", "node", NODE, "EA2ABC", None)
    assert fired.severity == "critical"
    assert fired.title == "EA2ABC ha desaparecido de la red"
    back = ae.render_alert_transition("node_offline", "resolved", "node", NODE, "EA2ABC", None)
    assert back.title == "EA2ABC ha reaparecido en la red"
    battery = ae.render_alert_transition("low_battery", "fired", "node", NODE, "EA2ABC", None)
    assert battery.severity == "warning"
    assert battery.title == "La batería de EA2ABC está baja"
    # gateway_disconnected se narra desde gateway.status, no desde la alerta
    assert ae.render_alert_transition("gateway_disconnected", "fired", "gateway", "gw-1", "gw-1", None) is None
    # reminder: no es una noticia nueva
    assert ae.render_alert_transition("node_offline", "reminder", "node", NODE, "EA2ABC", None) is None


def test_render_gateway_status_transitions_only():
    down = ae.render_gateway_status("gw-01", "Pico Almanzor", "disconnected", "usb", None)
    assert down.severity == "critical"
    assert down.title == "Gateway Pico Almanzor desconectado"
    up = ae.render_gateway_status("gw-01", None, "connected", "usb", None)
    assert up.title == "Gateway gw-01 conectado"
    assert ae.render_gateway_status("gw-01", None, "connecting", "usb", None) is None
    assert ae.render_gateway_status("gw-01", None, "reconnecting", "usb", None) is None


# ── Integración con IngestService (registro por paquete real) ───────────────


class Recorder:
    def __init__(self):
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)

    @property
    def diary(self) -> list[dict]:
        return [e["payload"] for e in self.events if e["event_type"] == "activity.event"]


async def test_ingest_node_info_always_plus_new_node_fact(session_factory):
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        await ingest.handle_event(make_event("node.seen", {"node_id": NODE, "short_name": "N1"}))
        # Repetido sin cambios: la entrada del paquete SIGUE apareciendo
        # (registro por paquete), sin hecho adicional la segunda vez
        await ingest.handle_event(make_event("node.seen", {"node_id": NODE, "short_name": "N1"}))
        # Cambio de identidad: entrada del paquete + hecho adicional
        await ingest.handle_event(make_event("node.seen", {"node_id": NODE, "short_name": "Refugio"}))
        # Snapshot de NodeDB (last_heard): excluido por completo
        await ingest.handle_event(
            make_event(
                "node.seen",
                {"node_id": "!00000002", "short_name": "N2", "last_heard": "2020-01-01T00:00:00+00:00"},
            )
        )
    finally:
        activity.attach(None)

    diary = recorder.diary
    # 1ª vez: paquete + hecho (nodo nuevo). 2ª vez (sin cambios): solo el
    # paquete, ningún hecho. 3ª vez (cambia el nombre): paquete + hecho.
    # El snapshot (4ª llamada) queda excluido por completo.
    assert len(diary) == 5
    assert [d["packet_type"] for d in diary] == [
        "Información del nodo",
        None,
        "Información del nodo",
        "Información del nodo",
        None,
    ]
    assert diary[1]["title"] == "N1 ha aparecido en la red por primera vez"
    assert diary[4]["title"] == "N1 ahora se identifica como «Refugio»"


async def test_ingest_new_node_fact_follows_its_packet_entry(session_factory):
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        await ingest.handle_event(make_event("node.seen", {"node_id": NODE, "short_name": "N1"}))
    finally:
        activity.attach(None)

    diary = recorder.diary
    assert len(diary) == 2
    assert diary[0]["packet_type"] == "Información del nodo"
    assert diary[1]["title"] == "N1 ha aparecido en la red por primera vez"
    assert diary[1]["packet_type"] is None


async def test_ingest_telemetry_never_fuses_kinds(session_factory):
    """Registro por paquete (Cambio 1 de la revisión anterior): cada paquete
    de telemetría es su propia entrada, con SOLO sus campos — nunca el
    estado combinado del nodo."""
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        await ingest.handle_event(
            make_event(
                "telemetry.received",
                {"node_id": NODE, "kind": "device", "battery_level": 91, "uptime_seconds": 82800},
            )
        )
        await ingest.handle_event(
            make_event(
                "telemetry.received",
                {"node_id": NODE, "kind": "environment", "temperature_c": 35.2},
            )
        )
    finally:
        activity.attach(None)

    diary = recorder.diary
    assert len(diary) == 2
    assert diary[0]["packet_type"] == "Telemetría del dispositivo"
    assert dict(map(tuple, diary[0]["details"]))["Batería"] == "91 %"
    assert "Temperatura" not in dict(map(tuple, diary[0]["details"]))
    assert diary[1]["packet_type"] == "Telemetría ambiental"
    assert dict(map(tuple, diary[1]["details"]))["Temperatura"] == "35.2 °C"
    assert "Batería" not in dict(map(tuple, diary[1]["details"]))


async def test_ingest_reboot_is_additional_entry_not_a_replacement(session_factory):
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        await ingest.handle_event(
            make_event(
                "telemetry.received",
                {"node_id": NODE, "kind": "device", "uptime_seconds": 100_000},
            )
        )
        await ingest.handle_event(
            make_event("telemetry.received", {"node_id": NODE, "kind": "device", "uptime_seconds": 12})
        )
    finally:
        activity.attach(None)

    diary = recorder.diary
    # 2 paquetes + 1 hecho de reinicio adicional = 3 entradas
    assert len(diary) == 3
    assert diary[0]["packet_type"] == "Telemetría del dispositivo"
    assert diary[1]["packet_type"] == "Telemetría del dispositivo"  # la entrada del paquete NUNCA se oculta
    assert diary[2]["title"].endswith("se ha reiniciado")
    assert diary[2]["severity"] == "critical"
    assert diary[2]["packet_type"] is None  # es un hecho, no un paquete


async def test_ingest_message_narrated_as_packet(session_factory):
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        await ingest.handle_event(make_event("node.seen", {"node_id": NODE, "short_name": "N1"}))
        await ingest.handle_event(
            make_event(
                "message.received",
                {"from_node_id": NODE, "text": "Hola, ¿qué tal?", "channel_index": 0, "rssi": -90},
            )
        )
    finally:
        activity.attach(None)

    msg = recorder.diary[-1]
    assert msg["packet_type"] == "Mensaje recibido"
    assert msg["description"] == "«Hola, ¿qué tal?»"
    assert msg["rssi"] == -90


async def test_ingest_neighbors_traceroute_waypoint(session_factory):
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        await ingest.handle_event(make_event("node.seen", {"node_id": NODE, "short_name": "N1"}))
        await ingest.handle_event(
            make_event(
                "neighbors.seen",
                {"node_id": NODE, "neighbors": [{"neighbor_id": "!00000002", "snr": -8.0}]},
            )
        )
        await ingest.handle_event(
            make_event("traceroute.completed", {"node_id": NODE, "route": [NODE, "!00000002"]})
        )
        await ingest.handle_event(
            make_event(
                "waypoint.shared",
                {"node_id": NODE, "name": "Refugio Sur", "latitude": 40.4, "longitude": -3.7},
            )
        )
    finally:
        activity.attach(None)

    diary = recorder.diary
    kinds = [d["packet_type"] for d in diary]
    assert "Información de vecinos" in kinds
    assert "Traceroute" in kinds
    assert "Waypoint compartido" in kinds
    neighbor_entry = next(d for d in diary if d["packet_type"] == "Información de vecinos")
    assert neighbor_entry["description"] == "1 vecinos detectados"
    trace_entry = next(d for d in diary if d["packet_type"] == "Traceroute")
    # El primer salto es el propio nodo (ya conocido: se resuelve a "N1")
    assert trace_entry["description"] == "N1 → !00000002"


async def test_ingest_gateway_transitions_only(session_factory):
    recorder = Recorder()
    activity.attach(recorder)
    try:
        ingest = IngestService(session_factory)
        connected = {"status": "connected", "transport": "usb"}
        await ingest.handle_event(make_event("gateway.status", connected, gateway_id="gw-01"))
        # Heartbeat sin cambio de estado: no es noticia
        await ingest.handle_event(make_event("gateway.status", connected, gateway_id="gw-01"))
        await ingest.handle_event(
            make_event("gateway.status", {"status": "disconnected", "transport": "usb"}, gateway_id="gw-01")
        )
    finally:
        activity.attach(None)

    titles = [d["title"] for d in recorder.diary]
    assert titles == ["Gateway gw-01 conectado", "Gateway gw-01 desconectado"]
    assert recorder.diary[1]["severity"] == "critical"
