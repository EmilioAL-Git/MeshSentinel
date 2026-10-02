"""Señales de actividad de la pasarela: respuesta del nodo, RX y TX LoRa

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-02

Tres sellos independientes en `gateways`: la pasarela está viva (el nodo
responde por el enlace API) es distinto de que haya tráfico LoRa RX o TX.
"""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

COLUMNS = ("last_device_response_at", "last_lora_rx_at", "last_lora_tx_at")


def upgrade() -> None:
    for col in COLUMNS:
        op.add_column("gateways", sa.Column(col, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in reversed(COLUMNS):
        op.drop_column("gateways", col)
