"""Entidades del Node Registry. Sin dependencias de infraestructura."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class Node:
    node_id: str
    node_num: int | None = None
    short_name: str | None = None
    long_name: str | None = None
    hw_model: str | None = None
    firmware_version: str | None = None
    role: str | None = None
    snr: float | None = None
    rssi: int | None = None
    hops_away: int | None = None
    via_mqtt: bool = False
    public_key: str | None = None
    gateway_id: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    # Metadatos del NOC (M1.2): solo BD propia, nunca tocan la malla
    is_favorite: bool = False
    is_ignored: bool = False

    def is_online(self, threshold_seconds: int, now: datetime | None = None) -> bool:
        if self.last_seen_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        last = self.last_seen_at
        if last.tzinfo is None:  # SQLite devuelve naive; el sistema persiste siempre UTC
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() <= threshold_seconds


@dataclass(slots=True)
class Position:
    node_id: str
    latitude: float
    longitude: float
    altitude_m: int | None = None
    precision_bits: int | None = None
    sats_in_view: int | None = None
    position_time: datetime | None = None
    received_at: datetime | None = None
    gateway_id: str | None = None


@dataclass(slots=True)
class Telemetry:
    node_id: str
    kind: str
    battery_level: int | None = None
    voltage: float | None = None
    channel_utilization: float | None = None
    air_util_tx: float | None = None
    uptime_seconds: int | None = None
    temperature_c: float | None = None
    relative_humidity: float | None = None
    barometric_pressure_hpa: float | None = None
    received_at: datetime | None = None
    gateway_id: str | None = None


@dataclass(slots=True)
class GatewayInfo:
    gateway_id: str
    status: str
    transport: str
    local_node_id: str | None = None
    detail: str | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Tag:
    name: str
    color: str | None = None
    id: int | None = None


@dataclass(slots=True)
class Group:
    name: str
    kind: str = "static"
    is_critical: bool = False
    member_count: int = 0
    id: int | None = None


@dataclass(slots=True)
class NodeSummary:
    """Vista agregada para el listado del NOC: nodo + últimos datos conocidos."""

    node: Node
    last_position: Position | None = None
    last_device_telemetry: Telemetry | None = None
    tags: list[Tag] = field(default_factory=list)
    group_ids: list[int] = field(default_factory=list)
