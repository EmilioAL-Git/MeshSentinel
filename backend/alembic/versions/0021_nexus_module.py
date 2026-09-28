"""JenTastic-Nexus: marcado manual de nodos (ADR 0027 §8)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-29

`nodes.is_nexus`: enteramente manual (mismo criterio que `is_favorite`/
`is_ignored`, M1.2) — nunca escrita por eventos de la malla, solo por
`PUT /nodes/{id}/nexus`, tras aceptar una sugerencia de `POST /nexus/scan`
o marcarlo directamente. El interruptor global "Modo Nexus/JenTastic"
reutiliza `system_settings` (migración 0020, clave/valor JSON genérico) —
sin migración propia.
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes", sa.Column("is_nexus", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("nodes", "is_nexus")
