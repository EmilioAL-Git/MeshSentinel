"""Recolección de trazas de la red real (ADR 0031)."""

from datetime import datetime, timedelta, timezone

from noc.adapters.persistence.repositories import SqlGatewayRepository
from noc.adapters.persistence.trace_repository import SqlTraceRepository
from noc.application.ingest import IngestService
from noc.application.traces import (
    UNKNOWN_NODE,
    extract_hops,
    trace_from_operation,
    trace_from_packet,
)
from noc.domain.nodes.entities import GatewayInfo

LOCAL, A, B, TARGET = "!00000001", "!0000000a", "!0000000b", "!000000ff"
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _packet(**over):
    base = {
        "node_id": TARGET,
        "to_node_id": LOCAL,
        "is_reply": True,
        "route": [A, B],
        "snr_towards": [5.0, -2.0, 7.5],
        "route_back": [B],
        "snr_back": [1.0, 3.0],
        "snr": 6.0,
        "rssi": -90,
    }
    base.update(over)
    return base


# ── Núcleo puro ──────────────────────────────────────────────────────────


def test_hops_ida_y_vuelta_con_snr_por_salto():
    hops = extract_hops(LOCAL, TARGET, [A, B], [5.0, -2.0, 7.5], [B], [1.0, 3.0])
    towards = [(h.src, h.dst, h.snr) for h in hops if h.direction == "towards"]
    back = [(h.src, h.dst, h.snr) for h in hops if h.direction == "back"]
    assert towards == [(LOCAL, A, 5.0), (A, B, -2.0), (B, TARGET, 7.5)]
    assert back == [(TARGET, B, 1.0), (B, LOCAL, 3.0)]


def test_traza_directa_es_una_sola_arista():
    hops = extract_hops(LOCAL, TARGET, [], [13.5], [], [])
    assert [(h.src, h.dst, h.snr) for h in hops] == [(LOCAL, TARGET, 13.5)]


def test_salto_desconocido_no_genera_arista_pero_conserva_el_resto():
    hops = extract_hops(LOCAL, TARGET, [UNKNOWN_NODE], [4.0, 6.0], [], [])
    assert hops == []  # ambos saltos tocan el nodo desconocido
    hops = extract_hops(LOCAL, TARGET, [A, UNKNOWN_NODE], [4.0, 6.0, 8.0], [], [])
    assert [(h.src, h.dst) for h in hops] == [(LOCAL, A)]


def test_snr_mas_corto_que_la_ruta_no_revienta():
    hops = extract_hops(LOCAL, TARGET, [A], [4.0], [], [])
    assert [h.snr for h in hops] == [4.0, None]


def test_respuesta_se_orienta_con_el_destinatario_como_origen():
    t = trace_from_packet(_packet(), gateway_id="gw", local_node_id=None, received_at=T0)
    assert (t.origin_id, t.target_id, t.kind) == (LOCAL, TARGET, "reply")
    assert t.source == "passive" and t.from_packet


def test_peticion_se_orienta_al_reves_y_cae_al_nodo_local():
    t = trace_from_packet(
        _packet(node_id=A, to_node_id=None, is_reply=False, route=[], route_back=[], snr_back=[]),
        gateway_id="gw", local_node_id=LOCAL, received_at=T0,
    )
    assert (t.origin_id, t.target_id, t.kind) == (A, LOCAL, "request")


def test_paquete_sin_destinatario_ni_nodo_local_se_descarta():
    assert trace_from_packet(_packet(to_node_id=None), gateway_id="gw", local_node_id=None, received_at=T0) is None


def test_operacion_sin_respuesta_es_evidencia_negativa_sin_aristas():
    t = trace_from_operation(
        {"reached": False, "error_reason": "NO_RESPONSE"},
        operation_id=7, gateway_id="gw", local_node_id=LOCAL, target_id=TARGET, finished_at=T0,
    )
    assert t.kind == "no_response" and not t.reached and t.hops == []


# ── Persistencia, fusión y grafo ─────────────────────────────────────────


async def _record(session_factory, trace):
    async with session_factory() as session, session.begin():
        return await SqlTraceRepository(session).record(trace)


def _active(at):
    return trace_from_operation(
        {"reached": True, "route": [A, B], "snr_towards": [5.0, -2.0, 7.5], "route_back": [B], "snr_back": [1.0, 3.0]},
        operation_id=9, gateway_id="gw", local_node_id=LOCAL, target_id=TARGET, finished_at=at,
    )


def _passive(at):
    return trace_from_packet(_packet(), gateway_id="gw", local_node_id=LOCAL, received_at=at)


async def test_activa_y_pasiva_de_la_misma_traza_se_fusionan_en_ambos_ordenes(session_factory):
    # paquete primero, resultado después
    _, created1 = await _record(session_factory, _passive(T0))
    _, created2 = await _record(session_factory, _active(T0 + timedelta(seconds=3)))
    assert (created1, created2) == (True, False)
    # resultado primero, paquete después (otra pareja, 10 min más tarde)
    t1 = T0 + timedelta(minutes=10)
    _, c3 = await _record(session_factory, _active(t1))
    _, c4 = await _record(session_factory, _passive(t1 + timedelta(seconds=2)))
    assert (c3, c4) == (True, False)
    async with session_factory() as session:
        rows = await SqlTraceRepository(session).list_recent()
        assert len(rows) == 2
        assert all(r.source == "active" and r.from_packet for r in rows)
        edges = await SqlTraceRepository(session).graph()
    # 5 aristas por traza, SIN duplicar los saltos por la fusión
    assert sum(e.observations for e in edges) == 10


async def test_dos_trazas_pasivas_cercanas_no_se_fusionan(session_factory):
    await _record(session_factory, _passive(T0))
    _, created = await _record(session_factory, _passive(T0 + timedelta(seconds=30)))
    assert created is True


async def test_grafo_agrega_snr_y_distingue_activas(session_factory):
    await _record(session_factory, _passive(T0))
    later = _passive(T0 + timedelta(hours=1))
    later.hops[0] = type(later.hops[0])(
        src=later.hops[0].src, dst=later.hops[0].dst, snr=9.0,
        direction=later.hops[0].direction, position=0,
    )
    await _record(session_factory, later)
    await _record(session_factory, _active(T0 + timedelta(hours=2)))
    async with session_factory() as session:
        edges = {(e.src_id, e.dst_id): e for e in await SqlTraceRepository(session).graph()}
    e = edges[(LOCAL, A)]
    assert e.observations == 3 and e.active_observations == 1
    assert e.min_snr == 5.0 and e.max_snr == 9.0 and e.last_snr == 5.0
    assert e.avg_snr == round((5.0 + 9.0 + 5.0) / 3, 2)
    # el sentido contrario es otra arista (dirigido)
    assert (A, LOCAL) not in edges


async def test_ingesta_pasiva_persiste_la_traza_con_el_nodo_local(session_factory):
    async with session_factory() as session, session.begin():
        await SqlGatewayRepository(session).upsert(
            GatewayInfo(gateway_id="gw-test", transport="simulated", status="connected", local_node_id=LOCAL, updated_at=T0)
        )
    await IngestService(session_factory).handle_event(
        {
            "schema_version": 1,
            "event_type": "traceroute.completed",
            "event_id": "e1",
            "gateway_id": "gw-test",
            "timestamp": T0.isoformat(),
            "payload": _packet(to_node_id=None),  # sin destinatario: cae al nodo local
        }
    )
    async with session_factory() as session:
        rows = await SqlTraceRepository(session).list_recent()
    assert len(rows) == 1 and rows[0].origin_id == LOCAL and rows[0].target_id == TARGET


async def test_listado_filtra_por_operacion(session_factory):
    await _record(session_factory, _passive(T0))
    await _record(session_factory, _active(T0 + timedelta(hours=1)))
    async with session_factory() as session:
        rows = await SqlTraceRepository(session).list_recent(operation_id=9)
        assert len(rows) == 1 and rows[0].operation_id == 9
        assert await SqlTraceRepository(session).list_recent(operation_id=404) == []


async def test_importacion_de_traceroutes_antiguos_es_idempotente(session_factory):
    from noc.adapters.persistence.activity_repositories import SqlActivityLogRepository
    from noc.application.traces_import import import_legacy_traces

    async with session_factory() as session, session.begin():
        await SqlGatewayRepository(session).upsert(
            GatewayInfo(gateway_id="gw", transport="simulated", status="connected", local_node_id=LOCAL, updated_at=T0)
        )

        def env(eid, raw, at):
            return {
                "event_id": eid, "gateway_id": "gw", "timestamp": at.isoformat(),
                "payload": {"node_id": TARGET, "source": "mesh", "severity": "info",
                            "internal_type": "TRACEROUTE_APP", "raw": raw},
            }

        await SqlActivityLogRepository(session).add_many([
            env("a", {"node_id": TARGET, "route": [A], "snr_towards": [20, -128]}, T0),
            env("b", {"node_id": TARGET, "route": [], "snr_towards": [54], "is_reply": True}, T0 + timedelta(hours=1)),
            env("c", {"node_id": TARGET, "route": [], "snr_towards": [8]}, T0 + timedelta(hours=2)),
        ])
    async with session_factory() as session, session.begin():
        first = await import_legacy_traces(session)
    async with session_factory() as session, session.begin():
        again = await import_legacy_traces(session)
        rows = await SqlTraceRepository(session).list_recent()
    assert first == {"scanned": 3, "imported": 2, "skipped": 1}  # "b" ya se registró en vivo
    assert again["imported"] == 0
    old = next(r for r in rows if r.route == [A])
    assert old.snr_towards == [5.0, None] and old.origin_id == LOCAL and old.route_back == []
