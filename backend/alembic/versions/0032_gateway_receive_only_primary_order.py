"""Pasarelas: solo recepción, primaria designada y orden manual

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-05

receive_only (manual) y tx_enabled (runtime, lo reporta el gateway) deciden si
una pasarela puede transmitir; is_primary designa la pasarela de último
recurso del enrutado; sort_order es el orden de presentación. ADR 0032.
"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.add_column(sa.Column("receive_only", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("tx_enabled", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.drop_column("sort_order")
        batch_op.drop_column("is_primary")
        batch_op.drop_column("tx_enabled")
        batch_op.drop_column("receive_only")
