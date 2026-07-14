from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from noc.application.dashboard import is_stale
from noc.domain.nodes.entities import (
    GatewayInfo,
    Node,
    NodeGatewayLink,
    NodeNeighbor,
    NodeSummary,
    Position,
    Tag,
    Telemetry,
)


class GatewaySelectionIn(BaseModel):
    """Selección inteligente de gateway (Nivel 1 de la jerarquía, ver
    `application/admin/gateway_routing.py`): único schema de request
    compartido por operaciones individuales y por lotes — evita tener tres
    implementaciones distintas del mismo selector.

    - "preferred" (por defecto): respeta preferencia de nodo/grupo, cae al
      automático si no está operativa — mismo resultado que hoy cuando no
      hay ninguna preferencia configurada (cero regresión).
    - "auto": ignora deliberadamente cualquier preferencia, algoritmo puro.
    - "forced": usa `gateway_id` siempre, sin comprobar disponibilidad.
    """

    mode: Literal["auto", "preferred", "forced"] = "preferred"
    gateway_id: str | None = None

    @model_validator(mode="after")
    def _forced_requires_gateway_id(self) -> "GatewaySelectionIn":
        if self.mode == "forced" and not self.gateway_id:
            raise ValueError("gateway_id es obligatorio cuando mode='forced'")
        return self


class PreferredGatewayIn(BaseModel):
    """Nivel 2/3 de la selección inteligente de gateway — mismo request en
    `PUT /nodes/{id}/preferred-gateway` y `PUT /groups/{id}/preferred-gateway`."""

    gateway_id: str | None = None


class NodeTypeIn(BaseModel):
    """Clasificación manual (Inspector, Organización): null = "Automático"."""

    node_type: Literal["gateway", "infra", "fixed", "user", "unclassified"] | None = None


class NodeTypeBulkIn(BaseModel):
    """Igual que NodeTypeIn pero para selección múltiple (Flota)."""

    node_ids: list[str]
    node_type: Literal["gateway", "infra", "fixed", "user", "unclassified"] | None = None


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
    preferred_gateway_id: str | None
    node_type_override: str | None
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


class NodeGatewayLinkOut(BaseModel):
    node_id: str
    gateway_id: str
    rssi: int | None
    snr: float | None
    hops_away: int | None
    via_mqtt: bool
    first_heard_at: datetime | None
    last_heard_at: datetime | None
    # M6.2: un enlace es "activo" con el mismo umbral que online/offline;
    # los enlaces stale se conservan (histórico de quién llegó a oír al nodo)
    # pero no cuentan para redundancia ni enrutado.
    active: bool = False
    # True si esta pasarela es la primaria actual del nodo (nodes.gateway_id)
    primary: bool = False

    @classmethod
    def from_entity(
        cls,
        link: NodeGatewayLink,
        offline_threshold: int | None = None,
        primary_gateway_id: str | None = None,
    ) -> "NodeGatewayLinkOut":
        data = {
            f: getattr(link, f) for f in cls.model_fields if f not in ("active", "primary")
        }
        active = (
            offline_threshold is not None
            and link.last_heard_at is not None
            and not is_stale(link.last_heard_at, offline_threshold)
        )
        return cls(**data, active=active, primary=link.gateway_id == primary_gateway_id)


class NeighborOut(BaseModel):
    """Enlace nodo<->nodo real (NEIGHBORINFO_APP), motor-de-reglas-y-topologia.md §2."""

    node_id: str
    neighbor_id: str
    snr: float | None
    received_at: datetime | None
    gateway_id: str | None
    # Mismo criterio que NodeGatewayLinkOut.active: vigente según el umbral
    # de offline, para que el mapa distinga topología viva de histórica.
    active: bool = False

    @classmethod
    def from_entity(cls, n: NodeNeighbor, offline_threshold: int | None = None) -> "NeighborOut":
        data = {f: getattr(n, f) for f in cls.model_fields if f != "active"}
        active = (
            offline_threshold is not None
            and n.received_at is not None
            and not is_stale(n.received_at, offline_threshold)
        )
        return cls(**data, active=active)


class NodeSummaryOut(BaseModel):
    node: NodeOut
    last_position: PositionOut | None
    last_device_telemetry: TelemetryOut | None
    tags: list[TagOut]
    group_ids: list[int]
    # M6.2: observaciones por pasarela (todas; `active` distingue las vigentes)
    gateway_links: list[NodeGatewayLinkOut] = []

    @classmethod
    def from_entity(
        cls,
        s: NodeSummary,
        online_threshold: int,
        gateway_links: list[NodeGatewayLink] | None = None,
    ) -> "NodeSummaryOut":
        return cls(
            node=NodeOut.from_entity(s.node, online_threshold),
            last_position=PositionOut.from_entity(s.last_position) if s.last_position else None,
            last_device_telemetry=(
                TelemetryOut.from_entity(s.last_device_telemetry) if s.last_device_telemetry else None
            ),
            tags=[TagOut.from_entity(t) for t in s.tags],
            group_ids=s.group_ids,
            gateway_links=[
                NodeGatewayLinkOut.from_entity(link, online_threshold, s.node.gateway_id)
                for link in (gateway_links or [])
            ],
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


