"""Ingesta de eventos del gateway (contrato shared/events v1) hacia persistencia.

Cada evento se procesa en su propia transacción: un evento malformado se
descarta con log y nunca interrumpe el flujo (el bus es fire-and-forget,
ADR 0003).
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNeighborRepository,
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.application import activity_events
from noc.application.activity import activity
from noc.application.dashboard import is_stale
from noc.application.gateway_link_selection import GatewayLinkCandidate, select_primary_link
from noc.domain.nodes.entities import (
    GatewayInfo,
    Node,
    NodeGatewayLink,
    NodeNeighbor,
    Position,
    Telemetry,
)

logger = logging.getLogger("noc.ingest")

SUPPORTED_SCHEMA_VERSION = 1

# Actividad 2.0 Fase 1: un uptime que retrocede más de esto respecto al último
# registro de kind=device se narra como reinicio, no como telemetría normal
REBOOT_UPTIME_DELTA_SECONDS = 60


def _node_label(node: Node | None, fallback: str) -> str:
    if node is not None and node.short_name:
        return node.short_name
    return fallback


def _parse_ts(value: str | None) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class IngestService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway_service: Any = None,
        gateway_stale_after_seconds: int = 90,
        node_offline_after_seconds: int = 900,
    ) -> None:
        self._session_factory = session_factory
        # M5 (ADR 0021 §5): reconciliación mínima si el proceso se reinicia con
        # una configuración gestionada pendiente. Opcional para no romper los
        # muchos tests que instancian IngestService sin estas dependencias.
        self._gateway_service = gateway_service
        self._gateway_stale_after_seconds = gateway_stale_after_seconds
        # M6.1: umbral para decidir qué enlaces nodo<->pasarela participan en
        # la selección de pasarela primaria (mismo umbral que online/offline,
        # ver docs/design/m6-multi-gateway.md §1.3).
        self._node_offline_after_seconds = node_offline_after_seconds

    async def handle_event(self, event: dict[str, Any]) -> None:
        if event.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            logger.warning("Unsupported schema_version: %r", event.get("schema_version"))
            return
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        gateway_id = event.get("gateway_id")
        received_at = _parse_ts(event.get("timestamp"))

        try:
            async with self._session_factory() as session, session.begin():
                match event_type:
                    case "node.seen":
                        await self._on_node_seen(session, payload, gateway_id, received_at)
                    case "position.updated":
                        await self._on_position(session, payload, gateway_id, received_at)
                    case "telemetry.received":
                        await self._on_telemetry(session, payload, gateway_id, received_at)
                    case "gateway.status":
                        await self._on_gateway_status(session, payload, gateway_id, received_at)
                    case "message.received":
                        await self._on_message(session, payload, gateway_id, received_at)
                    case "neighbors.seen":
                        await self._on_neighbors(session, payload, gateway_id, received_at)
                    case "traceroute.completed":
                        await self._on_traceroute(session, payload, gateway_id, received_at)
                    case "waypoint.shared":
                        await self._on_waypoint(session, payload, gateway_id, received_at)
                    case _:
                        logger.debug("Ignoring event_type=%s", event_type)
        except Exception:
            logger.exception("Failed to ingest event %s", event_type)

    async def _on_node_seen(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node_id = p["node_id"]
        node_repo = SqlNodeRepository(session)
        existing = await node_repo.get(node_id)
        node = Node(
            node_id=node_id,
            node_num=p.get("node_num"),
            short_name=p.get("short_name"),
            long_name=p.get("long_name"),
            hw_model=p.get("hw_model"),
            firmware_version=p.get("firmware_version"),
            role=p.get("role"),
            public_key=p.get("public_key"),
        )
        updated = await node_repo.upsert_from_sighting(node, ts)
        await self._narrate_node_seen(existing, updated, p, gateway_id)

        if not gateway_id:
            # Sin gateway_id no hay a qué pasarela atribuir el enlace; el
            # nodo ya quedó actualizado en su identidad, nada más que hacer.
            return

        link_repo = SqlNodeGatewayLinkRepository(session)
        await link_repo.upsert(
            NodeGatewayLink(
                node_id=node_id,
                gateway_id=gateway_id,
                rssi=p.get("rssi"),
                snr=p.get("snr"),
                hops_away=p.get("hops_away"),
                via_mqtt=p.get("via_mqtt", False),
                first_heard_at=ts,
                last_heard_at=ts,
            )
        )
        await self._recompute_gateway_cache(session, node_id, ts)

    async def _narrate_node_seen(
        self,
        existing: Node | None,
        updated: Node,
        p: dict[str, Any],
        gateway_id: str | None,
    ) -> None:
        """Registro por paquete: un NODEINFO_APP genera SIEMPRE su entrada
        ("Información del nodo"), haya o no novedad — más un hecho ADICIONAL
        (nunca en su lugar) cuando el nodo es nuevo o cambia de identidad.
        Los avistamientos del snapshot de NodeDB (`last_heard` presente) se
        excluyen de ambos: pueden ser muy antiguos y no son tráfico
        circulando ahora mismo."""
        if p.get("last_heard"):
            return
        label = _node_label(updated, updated.node_id)
        await activity.emit_activity(
            activity_events.render_node_info(updated.node_id, label, p, gateway_id)
        )

        if existing is None:
            fact = activity_events.render_new_node(
                updated.node_id, label, updated.hw_model, updated.firmware_version, gateway_id
            )
        elif p.get("short_name") is not None and p["short_name"] != existing.short_name:
            # Cubre también la primera identificación de un nodo descubierto
            # antes por telemetría/posición (existing.short_name aún None)
            fact = activity_events.render_identity_changed(
                updated.node_id, existing.short_name or existing.node_id, p["short_name"], gateway_id
            )
        else:
            return
        await activity.emit_activity(fact)

    async def _recompute_gateway_cache(self, session: AsyncSession, node_id: str, ts: datetime) -> None:
        """Recalcula la pasarela primaria de `nodes` (M6.1, §1.3/§3 del diseño).

        Con una única pasarela esto es un no-op: `select_primary_link` solo
        tiene un candidato y siempre lo elige, dejando la caché idéntica a
        lo que escribía antes directamente `upsert_from_sighting`.
        """
        links = await SqlNodeGatewayLinkRepository(session).list_for_node(node_id)
        active_links = [
            link
            for link in links
            if not is_stale(link.last_heard_at, self._node_offline_after_seconds, now=ts)
        ]
        if not active_links:
            return

        gateway_repo = SqlGatewayRepository(session)
        links_by_gateway = {link.gateway_id: link for link in active_links}
        candidates = []
        for link in active_links:
            info = await gateway_repo.get(link.gateway_id)
            candidates.append(
                GatewayLinkCandidate(
                    gateway_id=link.gateway_id,
                    last_heard_at=link.last_heard_at,  # type: ignore[arg-type]
                    priority=info.priority if info is not None else 0,
                    hops_away=link.hops_away,
                    snr=link.snr,
                    rssi=link.rssi,
                )
            )

        winner = select_primary_link(candidates)
        if winner is None:
            return
        chosen = links_by_gateway[winner.gateway_id]
        await SqlNodeRepository(session).apply_gateway_cache(
            node_id,
            gateway_id=chosen.gateway_id,
            rssi=chosen.rssi,
            snr=chosen.snr,
            hops_away=chosen.hops_away,
            via_mqtt=chosen.via_mqtt,
        )

    async def _on_position(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node_repo = SqlNodeRepository(session)
        await node_repo.touch_last_seen(p["node_id"], gateway_id, ts)
        position_time = p.get("position_time")
        await SqlPositionRepository(session).add(
            Position(
                node_id=p["node_id"],
                latitude=p["latitude"],
                longitude=p["longitude"],
                altitude_m=p.get("altitude_m"),
                precision_bits=p.get("precision_bits"),
                sats_in_view=p.get("sats_in_view"),
                position_time=_parse_ts(position_time) if position_time else None,
                received_at=ts,
                gateway_id=gateway_id,
            )
        )
        label = _node_label(await node_repo.get(p["node_id"]), p["node_id"])
        await activity.emit_activity(
            activity_events.render_position(p["node_id"], label, p, gateway_id)
        )

    async def _on_telemetry(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node_repo = SqlNodeRepository(session)
        telemetry_repo = SqlTelemetryRepository(session)
        await node_repo.touch_last_seen(p["node_id"], gateway_id, ts)

        # Reinicio (Fase 1 §4): comparar el uptime nuevo con el del registro
        # de kind=device inmediatamente ANTERIOR a insertar la fila nueva
        rebooted = False
        new_uptime = p.get("uptime_seconds")
        if p["kind"] == "device" and new_uptime is not None:
            previous = await telemetry_repo.list_for_node(p["node_id"], 1, "device")
            prev_uptime = previous[0].uptime_seconds if previous else None
            rebooted = (
                prev_uptime is not None
                and prev_uptime - new_uptime > REBOOT_UPTIME_DELTA_SECONDS
            )

        await telemetry_repo.add(
            Telemetry(
                node_id=p["node_id"],
                kind=p["kind"],
                battery_level=p.get("battery_level"),
                voltage=p.get("voltage"),
                channel_utilization=p.get("channel_utilization"),
                air_util_tx=p.get("air_util_tx"),
                uptime_seconds=p.get("uptime_seconds"),
                temperature_c=p.get("temperature_c"),
                relative_humidity=p.get("relative_humidity"),
                barometric_pressure_hpa=p.get("barometric_pressure_hpa"),
                received_at=ts,
                gateway_id=gateway_id,
            )
        )

        # Registro por paquete: la entrada describe SOLO el paquete que llegó
        # (un kind = una entrada, nunca fusionada con otros kinds del nodo).
        # El reinicio es un hecho ADICIONAL, nunca sustituye a la entrada.
        #
        # Excepción (pedida por el usuario): la telemetría de dispositivo del
        # NODO LOCAL del gateway que la reporta NO se narra — el nodo se
        # auto-reporta por la API con mucha frecuencia (ni siquiera es
        # tráfico LoRa) e inunda el diario. Se sigue persistiendo igual
        # (histórico, dashboard, alertas); solo se calla la entrada. El
        # reinicio del nodo local SÍ se narra (hecho relevante), y la
        # telemetría de un nodo gateway oída por OTRA pasarela también
        # (eso sí es tráfico de malla real).
        label = _node_label(await node_repo.get(p["node_id"]), p["node_id"])
        is_own_gateway_node = (
            p["kind"] == "device"
            and gateway_id is not None
            and await self._is_local_node_of(session, gateway_id, p["node_id"])
        )
        if not is_own_gateway_node:
            packet_event = activity_events.render_telemetry_packet(
                p["kind"], p["node_id"], label, p, gateway_id
            )
            if packet_event is not None:
                await activity.emit_activity(packet_event)
        if rebooted:
            await activity.emit_activity(
                activity_events.render_reboot(p["node_id"], label, new_uptime, gateway_id)
            )

    @staticmethod
    async def _is_local_node_of(session: AsyncSession, gateway_id: str, node_id: str) -> bool:
        info = await SqlGatewayRepository(session).get(gateway_id)
        return info is not None and info.local_node_id == node_id

    async def _on_message(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node_repo = SqlNodeRepository(session)
        from_id = p["from_node_id"]
        await node_repo.touch_last_seen(from_id, gateway_id, ts)
        label = _node_label(await node_repo.get(from_id), from_id)
        to_id = p.get("to_node_id")
        to_label = _node_label(await node_repo.get(to_id), to_id) if to_id else None
        await activity.emit_activity(
            activity_events.render_message(from_id, label, p, to_label, gateway_id)
        )

    async def _on_neighbors(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        """NEIGHBORINFO_APP: persiste cada vecino directo en `node_neighbors`
        (topología real de malla, motor-de-reglas-y-topologia.md §2) además
        de narrar el paquete, mismo orden que `_on_position` (persistir
        primero, narrar después)."""
        node_repo = SqlNodeRepository(session)
        neighbor_repo = SqlNeighborRepository(session)
        node_id = p["node_id"]
        await node_repo.touch_last_seen(node_id, gateway_id, ts)
        neighbor_labels: list[tuple[str, float | None]] = []
        for n in p.get("neighbors") or []:
            await neighbor_repo.add(
                NodeNeighbor(
                    node_id=node_id,
                    neighbor_id=n["neighbor_id"],
                    snr=n.get("snr"),
                    received_at=ts,
                    gateway_id=gateway_id,
                )
            )
            neighbor_labels.append(
                (_node_label(await node_repo.get(n["neighbor_id"]), n["neighbor_id"]), n.get("snr"))
            )
        label = _node_label(await node_repo.get(node_id), node_id)
        await activity.emit_activity(
            activity_events.render_neighbor_info(node_id, label, neighbor_labels, gateway_id, p)
        )

    async def _on_traceroute(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node_repo = SqlNodeRepository(session)
        node_id = p["node_id"]
        await node_repo.touch_last_seen(node_id, gateway_id, ts)
        label = _node_label(await node_repo.get(node_id), node_id)
        route_labels = [
            _node_label(await node_repo.get(hop_id), hop_id) for hop_id in p.get("route") or []
        ]
        await activity.emit_activity(
            activity_events.render_traceroute(node_id, label, route_labels, gateway_id, p)
        )

    async def _on_waypoint(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node_repo = SqlNodeRepository(session)
        node_id = p["node_id"]
        await node_repo.touch_last_seen(node_id, gateway_id, ts)
        label = _node_label(await node_repo.get(node_id), node_id)
        await activity.emit_activity(
            activity_events.render_waypoint(node_id, label, p, gateway_id)
        )

    async def _on_gateway_status(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        if not gateway_id:
            return
        repo = SqlGatewayRepository(session)
        previous = await repo.get(gateway_id)
        was_stale = previous is None or is_stale(previous.updated_at, self._gateway_stale_after_seconds, now=ts)
        info = await repo.upsert(
            GatewayInfo(
                gateway_id=gateway_id,
                status=p.get("status", "unknown"),
                transport=p.get("transport", "unknown"),
                local_node_id=p.get("local_node_id"),
                detail=p.get("detail"),
                updated_at=ts,
                local_short_name=p.get("local_short_name"),
                local_long_name=p.get("local_long_name"),
                local_hw_model=p.get("local_hw_model"),
                local_firmware_version=p.get("local_firmware_version"),
            )
        )
        # Diario operativo (Actividad 2.0 Fase 1): narrar SOLO transiciones de
        # estado, nunca el heartbeat periódico — y al instante, sin esperar a
        # que la regla gateway_disconnected confirme la caída con su margen.
        new_status = p.get("status", "unknown")
        if previous is None or previous.status != new_status:
            event = activity_events.render_gateway_status(
                gateway_id, info.name, new_status, p.get("transport"), p.get("detail")
            )
            if event is not None:
                await activity.emit_activity(event)

        # Reconciliación (ADR 0021 §5): el proceso probablemente acaba de
        # (re)arrancar con la config de .env, perdiendo la gestionada — se
        # reenvía el comando de conexión (Redis, no toca esta transacción).
        if was_stale and self._gateway_service is not None:
            await self._gateway_service.reconcile_after_heartbeat(info)
