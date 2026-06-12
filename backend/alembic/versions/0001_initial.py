"""Esquema inicial: gateways, nodes, node_positions, node_telemetry

Revision ID: 0001
Revises:
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateways",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("local_node_id", sa.String(16), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("node_num", sa.BigInteger(), nullable=True),
        sa.Column("short_name", sa.String(8), nullable=True),
        sa.Column("long_name", sa.String(64), nullable=True),
        sa.Column("hw_model", sa.String(32), nullable=True),
        sa.Column("firmware_version", sa.String(32), nullable=True),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("rssi", sa.Integer(), nullable=True),
        sa.Column("hops_away", sa.Integer(), nullable=True),
        sa.Column("via_mqtt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_key", sa.Text(), nullable=True),
        sa.Column("gateway_id", sa.String(64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_nodes_last_seen_at", "nodes", ["last_seen_at"])

    op.create_table(
        "node_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("altitude_m", sa.Integer(), nullable=True),
        sa.Column("precision_bits", sa.Integer(), nullable=True),
        sa.Column("sats_in_view", sa.Integer(), nullable=True),
        sa.Column("position_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gateway_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_node_positions_node_received", "node_positions", ["node_id", "received_at"])

    op.create_table(
        "node_telemetry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("battery_level", sa.Integer(), nullable=True),
        sa.Column("voltage", sa.Float(), nullable=True),
        sa.Column("channel_utilization", sa.Float(), nullable=True),
        sa.Column("air_util_tx", sa.Float(), nullable=True),
        sa.Column("uptime_seconds", sa.BigInteger(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("relative_humidity", sa.Float(), nullable=True),
        sa.Column("barometric_pressure_hpa", sa.Float(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gateway_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_node_telemetry_node_received", "node_telemetry", ["node_id", "received_at"])


def downgrade() -> None:
    op.drop_table("node_telemetry")
    op.drop_table("node_positions")
    op.drop_index("ix_nodes_last_seen_at", table_name="nodes")
    op.drop_table("nodes")
    op.drop_table("gateways")
