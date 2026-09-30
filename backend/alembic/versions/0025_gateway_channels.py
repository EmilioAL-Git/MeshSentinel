"""gateways.channels: caché de nombres de canal del nodo local

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-30

Nombres reales de canal en el Registro/Chat (índice -> nombre), refrescados
en cada conexión igual que local_short_name/local_long_name (M5). Con varias
pasarelas se fusionan en `application/channel_names.py` (prioridad manual y,
en empate, gateway_id ascendente).
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.add_column(
            sa.Column("channels", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.drop_column("channels")
