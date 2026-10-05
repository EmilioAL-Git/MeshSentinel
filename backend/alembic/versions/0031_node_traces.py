"""Trazas de la red real (traceroute)

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-05

node_traces (una fila por traza observada, activa o pasiva) y
node_trace_hops (una arista dirigida por salto, para agregar el grafo con
GROUP BY). Append-only, como node_positions/node_neighbors. ADR 0031.
"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_traces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gateway_id", sa.String(64), nullable=True),
        sa.Column("origin_id", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(16), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reached", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("route", sa.JSON(), nullable=False),
        sa.Column("route_back", sa.JSON(), nullable=False),
        sa.Column("snr_towards", sa.JSON(), nullable=False),
        sa.Column("snr_back", sa.JSON(), nullable=False),
        sa.Column("operation_id", sa.Integer(), nullable=True),
        sa.Column("from_packet", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_node_traces_received", "node_traces", ["received_at"])
    op.create_index("ix_node_traces_target_received", "node_traces", ["target_id", "received_at"])
    op.create_index("ix_node_traces_origin_received", "node_traces", ["origin_id", "received_at"])
    op.create_table(
        "node_trace_hops",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.Integer(), sa.ForeignKey("node_traces.id"), nullable=False),
        sa.Column("src_id", sa.String(16), nullable=False),
        sa.Column("dst_id", sa.String(16), nullable=False),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_node_trace_hops_pair", "node_trace_hops", ["src_id", "dst_id", "received_at"])
    op.create_index("ix_node_trace_hops_trace", "node_trace_hops", ["trace_id"])
    op.create_index("ix_node_trace_hops_received", "node_trace_hops", ["received_at"])


def downgrade() -> None:
    op.drop_table("node_trace_hops")
    op.drop_table("node_traces")
