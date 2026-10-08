"""Silenciar alertas por nodo

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as b:
        b.add_column(sa.Column("alerts_muted", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("nodes") as b:
        b.drop_column("alerts_muted")
