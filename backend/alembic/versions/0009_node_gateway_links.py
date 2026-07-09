"""M6.1: node_gateway_links — N:M nodo<->pasarela con backfill

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-10

Tabla aditiva (ver docs/design/m6-multi-gateway.md §1.3/§12): estado actual
de la relación, no histórico. `nodes.gateway_id`/`rssi`/`snr`/`hops_away`
siguen siendo la caché derivada que ya usa el resto del sistema — esta
migración no los toca ni los elimina.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_gateway_links",
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("gateway_id", sa.String(64), primary_key=True),
        sa.Column("rssi", sa.Integer(), nullable=True),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("hops_away", sa.Integer(), nullable=True),
        sa.Column("via_mqtt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_heard_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heard_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_node_gateway_links_last_heard_at", "node_gateway_links", ["last_heard_at"])

    # Backfill (§1.3/§12): una fila por nodo ya existente con gateway_id
    # conocido, copiando el estado actual de `nodes` — instalaciones de una
    # sola pasarela quedan con exactamente una fila por nodo, sin pérdida de
    # datos y sin cambio de comportamiento observable.
    op.execute(
        sa.text(
            """
            INSERT INTO node_gateway_links
                (node_id, gateway_id, rssi, snr, hops_away, via_mqtt, first_heard_at, last_heard_at)
            SELECT id, gateway_id, rssi, snr, hops_away, via_mqtt, first_seen_at, last_seen_at
            FROM nodes
            WHERE gateway_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_node_gateway_links_last_heard_at", table_name="node_gateway_links")
    op.drop_table("node_gateway_links")
