"""Recepciones directas medidas para la cobertura real

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-06

Append-only: una fila por posición oída a 0 saltos con SNR. ADR 0035.
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coverage_receptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gateway_id", sa.String(64), nullable=False),
        sa.Column("node_id", sa.String(16), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("rssi", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_coverage_received", "coverage_receptions", ["received_at"])
    op.create_index("ix_coverage_gateway_received", "coverage_receptions", ["gateway_id", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_coverage_gateway_received", table_name="coverage_receptions")
    op.drop_index("ix_coverage_received", table_name="coverage_receptions")
    op.drop_table("coverage_receptions")
