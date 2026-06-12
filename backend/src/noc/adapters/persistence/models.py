from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from noc.adapters.persistence.database import Base


class GatewayModel(Base):
    __tablename__ = "gateways"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    transport: Mapped[str] = mapped_column(String(16))
    local_node_id: Mapped[str | None] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NodeModel(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    node_num: Mapped[int | None] = mapped_column(BigInteger)
    short_name: Mapped[str | None] = mapped_column(String(8))
    long_name: Mapped[str | None] = mapped_column(String(64))
    hw_model: Mapped[str | None] = mapped_column(String(32))
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(32))
    snr: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[int | None] = mapped_column(Integer)
    hops_away: Mapped[int | None] = mapped_column(Integer)
    via_mqtt: Mapped[bool] = mapped_column(Boolean, default=False)
    public_key: Mapped[str | None] = mapped_column(Text)
    gateway_id: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PositionModel(Base):
    __tablename__ = "node_positions"
    __table_args__ = (Index("ix_node_positions_node_received", "node_id", "received_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude_m: Mapped[int | None] = mapped_column(Integer)
    precision_bits: Mapped[int | None] = mapped_column(Integer)
    sats_in_view: Mapped[int | None] = mapped_column(Integer)
    position_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gateway_id: Mapped[str | None] = mapped_column(String(64))


class TelemetryModel(Base):
    __tablename__ = "node_telemetry"
    __table_args__ = (Index("ix_node_telemetry_node_received", "node_id", "received_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16))
    battery_level: Mapped[int | None] = mapped_column(Integer)
    voltage: Mapped[float | None] = mapped_column(Float)
    channel_utilization: Mapped[float | None] = mapped_column(Float)
    air_util_tx: Mapped[float | None] = mapped_column(Float)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    relative_humidity: Mapped[float | None] = mapped_column(Float)
    barometric_pressure_hpa: Mapped[float | None] = mapped_column(Float)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gateway_id: Mapped[str | None] = mapped_column(String(64))
