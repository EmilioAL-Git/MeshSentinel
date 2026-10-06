"""Operaciones fallidas descartables

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admin_operations") as b:
        b.add_column(sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("admin_operations") as b:
        b.drop_column("dismissed_at")
