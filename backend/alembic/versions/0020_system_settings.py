"""Ajustes: system_settings (overrides en BD de umbrales operacionales)

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-15

Panel "Ajustes" (pedido por el usuario tras preguntar cómo se calcula
online/offline): tabla clave/valor de overrides sobre `noc.config.Settings`.
Ausencia de fila = sigue el default de env/literal, sin cambio de
comportamiento para instalaciones existentes. Solo cubre umbrales
operacionales del backend (red/nodos, motor de alertas, administración
remota, actividad) — wiring de infraestructura (BD, Redis, CORS...) y los
defaults de fábrica por rule_type del motor de alertas quedan fuera a
propósito (decisión del usuario).
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
