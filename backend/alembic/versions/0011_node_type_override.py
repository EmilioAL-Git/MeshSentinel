"""Clasificación manual de nodo (Inspector, Organización)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-11

Columna aditiva nullable, sin cambio de comportamiento por defecto (NULL =
"Automático" = misma clasificación derivada del role de firmware que hasta
ahora, ver `frontend/src/components/fleet/classify.ts`). Valores manuales
comparten vocabulario exacto con `FleetCategory`: gateway | infra | fixed |
user | unclassified.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("node_type_override", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "node_type_override")
