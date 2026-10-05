"""Pasarelas: estado runtime del nodo virtual

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-05

`virtual_node` ({port, clients, allow_admin} o NULL): lo reporta el gateway en
su heartbeat; la configuración vive en connection_params (vn_*). ADR 0033.
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.add_column(sa.Column("virtual_node", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.drop_column("virtual_node")
