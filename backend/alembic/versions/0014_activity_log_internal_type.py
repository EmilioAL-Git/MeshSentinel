"""activity_log gana internal_type extraído, filtrable sin JSON

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-13

Permite reconstruir la capa "Rutas" del mapa (traceroutes históricos) desde
activity_log filtrando por internal_type="TRACEROUTE_APP" sin excavar JSON
dialectal. Columna nullable, sin backfill: activity_log es de la fase de
hardening anterior, aún sin validar en producción por el usuario.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activity_log", sa.Column("internal_type", sa.String(32), nullable=True))
    op.create_index(
        "ix_activity_log_internal_type_created",
        "activity_log",
        ["internal_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_log_internal_type_created", table_name="activity_log")
    op.drop_column("activity_log", "internal_type")
