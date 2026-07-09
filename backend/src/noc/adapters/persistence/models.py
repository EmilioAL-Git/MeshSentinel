from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
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
    # Metadatos del NOC (M1.2) — nunca provienen de la malla ni la modifican
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ignored: Mapped[bool] = mapped_column(Boolean, default=False)


class TagModel(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    color: Mapped[str | None] = mapped_column(String(16))


class NodeTagModel(Base):
    __tablename__ = "node_tags"

    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class GroupModel(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="static")
    filter_expr: Mapped[str | None] = mapped_column(Text)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)


class GroupMemberModel(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)


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


class AlertRuleModel(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_status_fired", "status", "fired_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128))
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    correlation_key: Mapped[str | None] = mapped_column(String(128), index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminBatchModel(Base):
    __tablename__ = "admin_batches"
    __table_args__ = (Index("ix_admin_batches_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    operation_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    node_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    scope_description: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminOperationModel(Base):
    __tablename__ = "admin_operations"
    __table_args__ = (
        Index("ix_admin_ops_status_next", "status", "next_attempt_at"),
        Index("ix_admin_ops_node_created", "target_node_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_batches.id"), nullable=True, index=True
    )
    target_node_id: Mapped[str] = mapped_column(String(16))
    gateway_id: Mapped[str] = mapped_column(String(64))
    operation_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class NotificationChannelModel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    channel_type: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


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
