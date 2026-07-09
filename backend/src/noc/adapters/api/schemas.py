from datetime import datetime

from pydantic import BaseModel

from noc.domain.nodes.entities import GatewayInfo, Node, NodeSummary, Position, Tag, Telemetry


class PositionOut(BaseModel):
    node_id: str
    latitude: float
    longitude: float
    altitude_m: int | None
    precision_bits: int | None
    sats_in_view: int | None
    position_time: datetime | None
    received_at: datetime | None
    gateway_id: str | None

    @classmethod
    def from_entity(cls, p: Position) -> "PositionOut":
        return cls(**{f: getattr(p, f) for f in cls.model_fields})


class TelemetryOut(BaseModel):
    node_id: str
    kind: str
    battery_level: int | None
    voltage: float | None
    channel_utilization: float | None
    air_util_tx: float | None
    uptime_seconds: int | None
    temperature_c: float | None
    relative_humidity: float | None
    barometric_pressure_hpa: float | None
    received_at: datetime | None
    gateway_id: str | None

    @classmethod
    def from_entity(cls, t: Telemetry) -> "TelemetryOut":
        return cls(**{f: getattr(t, f) for f in cls.model_fields})


class NodeOut(BaseModel):
    node_id: str
    node_num: int | None
    short_name: str | None
    long_name: str | None
    hw_model: str | None
    firmware_version: str | None
    role: str | None
    snr: float | None
    rssi: int | None
    hops_away: int | None
    via_mqtt: bool
    gateway_id: str | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    is_favorite: bool
    is_ignored: bool
    online: bool

    @classmethod
    def from_entity(cls, n: Node, online_threshold: int) -> "NodeOut":
        data = {f: getattr(n, f) for f in cls.model_fields if f != "online"}
        return cls(**data, online=n.is_online(online_threshold))


class TagOut(BaseModel):
    id: int
    name: str
    color: str | None

    @classmethod
    def from_entity(cls, t: Tag) -> "TagOut":
        return cls(id=t.id or 0, name=t.name, color=t.color)


class NodeSummaryOut(BaseModel):
    node: NodeOut
    last_position: PositionOut | None
    last_device_telemetry: TelemetryOut | None
    tags: list[TagOut]
    group_ids: list[int]

    @classmethod
    def from_entity(cls, s: NodeSummary, online_threshold: int) -> "NodeSummaryOut":
        return cls(
            node=NodeOut.from_entity(s.node, online_threshold),
            last_position=PositionOut.from_entity(s.last_position) if s.last_position else None,
            last_device_telemetry=(
                TelemetryOut.from_entity(s.last_device_telemetry) if s.last_device_telemetry else None
            ),
            tags=[TagOut.from_entity(t) for t in s.tags],
            group_ids=s.group_ids,
        )


class GatewayOut(BaseModel):
    gateway_id: str
    status: str
    transport: str
    local_node_id: str | None
    detail: str | None
    updated_at: datetime | None
    local_short_name: str | None
    local_long_name: str | None
    local_hw_model: str | None
    local_firmware_version: str | None
    name: str | None
    managed: bool
    transport_type: str | None
    connection_params: dict
    enabled: bool
    priority: int
    desired_status: str
    deleted_at: datetime | None
    last_connected_at: datetime | None
    last_disconnected_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None

    @classmethod
    def from_entity(cls, g: GatewayInfo) -> "GatewayOut":
        return cls(**{f: getattr(g, f) for f in cls.model_fields})
