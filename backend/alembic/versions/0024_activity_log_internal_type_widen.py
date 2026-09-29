"""activity_log.internal_type: VARCHAR(32) -> VARCHAR(64)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-29

Bug real encontrado en producción: "TELEMETRY_APP (environmentMetrics)"
(35 caracteres) supera el VARCHAR(32) original (pensado para valores como
"TRACEROUTE_APP") y Postgres rechaza el INSERT en bloque
(StringDataRightTruncationError) en vez de truncar en silencio como MySQL
-> cada flush de telemetría de entorno pierde su lote entero del
ActivityLogWriter (`activity_log flush failed (N events lost)`). 64
caracteres da margen sin necesidad de acortar las etiquetas legibles ya
en producción.
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "activity_log", "internal_type",
        type_=sa.String(64), existing_type=sa.String(32), existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "activity_log", "internal_type",
        type_=sa.String(32), existing_type=sa.String(64), existing_nullable=True,
    )
