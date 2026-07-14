"""Topología: node_neighbors — enlaces nodo<->nodo reales (NeighborInfo)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-13

Ingesta de NEIGHBORINFO_APP (diseñada en docs/design/motor-de-reglas-y-
topologia.md §2, ya decodificada por el gateway desde "Actividad 2.0 —
registro por paquete" pero solo narrada, nunca persistida). Append-only,
mismo patrón que node_positions/node_telemetry: "lo último" por par
(node_id, neighbor_id) se resuelve con row_number(), nunca se pisa.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_neighbors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("neighbor_id", sa.String(16), nullable=False),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gateway_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_node_neighbors_node_received", "node_neighbors", ["node_id", "received_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_node_neighbors_node_received", table_name="node_neighbors")
    op.drop_table("node_neighbors")
