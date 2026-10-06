"""Posiciones estimadas para nodos sin GPS

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-06

Estado derivado (una fila por nodo, reemplazada en cada pasada del estimador). ADR 0035.
"""
from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "estimated_positions",
        sa.Column("node_id", sa.String(16), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False),
        sa.Column("anchors", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("estimated_positions")
