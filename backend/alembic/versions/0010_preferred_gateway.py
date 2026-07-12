"""Selección inteligente de gateway: preferencia de nodo/grupo + nota en operación

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-11

Tres columnas aditivas, todas nullable, sin cambio de comportamiento por
defecto (NULL = sin preferencia = mismo algoritmo automático de M6.2):
- `nodes.preferred_gateway_id` (Nivel 2 de la jerarquía de resolución)
- `groups.preferred_gateway_id` (Nivel 3)
- `admin_operations.gateway_note` (motivo legible cuando la pasarela
  resuelta no fue la preferida por no estar operativa)
Sin FK, mismo criterio que `nodes.gateway_id`/`admin_operations.gateway_id`
ya existentes: pueden referenciar una pasarela sin fila propia todavía.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("preferred_gateway_id", sa.String(64), nullable=True))
    op.add_column("groups", sa.Column("preferred_gateway_id", sa.String(64), nullable=True))
    op.add_column("admin_operations", sa.Column("gateway_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_operations", "gateway_note")
    op.drop_column("groups", "preferred_gateway_id")
    op.drop_column("nodes", "preferred_gateway_id")
