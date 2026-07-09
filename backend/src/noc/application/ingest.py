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
    SqlNodeRepository,
    SqlPositionRepository,
    SqlTelemetryRepository,
)
from noc.application.dashboard import is_stale
from noc.domain.nodes.entities import GatewayInfo, Node, Position, Telemetry

logger = logging.getLogger("noc.ingest")

SUPPORTED_SCHEMA_VERSION = 1


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
    ) -> None:
        self._session_factory = session_factory
        # M5 (ADR 0021 §5): reconciliación mínima si el proceso se reinicia con
        # una configuración gestionada pendiente. Opcional para no romper los
        # muchos tests que instancian IngestService sin estas dependencias.
        self._gateway_service = gateway_service
        self._gateway_stale_after_seconds = gateway_stale_after_seconds

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
                        await SqlNodeRepository(session).touch_last_seen(
                            payload["from_node_id"], gateway_id, received_at
                        )
                    case _:
                        logger.debug("Ignoring event_type=%s", event_type)
        except Exception:
            logger.exception("Failed to ingest event %s", event_type)

    async def _on_node_seen(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        node = Node(
            node_id=p["node_id"],
            node_num=p.get("node_num"),
            short_name=p.get("short_name"),
            long_name=p.get("long_name"),
            hw_model=p.get("hw_model"),
            firmware_version=p.get("firmware_version"),
            role=p.get("role"),
            snr=p.get("snr"),
            rssi=p.get("rssi"),
            hops_away=p.get("hops_away"),
            via_mqtt=p.get("via_mqtt", False),
            public_key=p.get("public_key"),
            gateway_id=gateway_id,
        )
        await SqlNodeRepository(session).upsert_from_sighting(node, ts)

    async def _on_position(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        await SqlNodeRepository(session).touch_last_seen(p["node_id"], gateway_id, ts)
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

    async def _on_telemetry(
        self, session: AsyncSession, p: dict[str, Any], gateway_id: str | None, ts: datetime
    ) -> None:
        await SqlNodeRepository(session).touch_last_seen(p["node_id"], gateway_id, ts)
        await SqlTelemetryRepository(session).add(
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
        # Reconciliación (ADR 0021 §5): el proceso probablemente acaba de
        # (re)arrancar con la config de .env, perdiendo la gestionada — se
        # reenvía el comando de conexión (Redis, no toca esta transacción).
        if was_stale and self._gateway_service is not None:
            await self._gateway_service.reconcile_after_heartbeat(info)
