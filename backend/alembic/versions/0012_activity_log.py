"""Hardening: activity_log — registro persistente del diario operativo

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-13

El Registro deja de vivir solo en el buffer del navegador: cada envelope
`activity.event` (el mismo que viaja por el WebSocket) se persiste para que
la vista pueda sembrarse al recargar. Append-only con poda por tamaño máximo
(NOC_ACTIVITY_LOG_MAX_ROWS) desde el escritor en background — no un histórico
ilimitado.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("gateway_id", sa.String(64), nullable=True),
        sa.Column("node_id", sa.String(16), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])
    op.create_index("ix_activity_log_node_created", "activity_log", ["node_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_activity_log_node_created", table_name="activity_log")
    op.drop_index("ix_activity_log_created_at", table_name="activity_log")
    op.drop_table("activity_log")
