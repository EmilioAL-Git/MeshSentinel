"""Motor de reglas §1: alert_rules.group_id — reglas por grupo

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-15

Opción A de docs/design/motor-de-reglas-y-topologia.md §1.3 (recomendada y
alineada con lo que pidió el usuario: umbrales distintos por grupo, no solo
el filtrado client-side que ya existía). NULL = regla global (comportamiento
actual, sin migración de datos). Sin ForeignKey, mismo criterio que
nodes.preferred_gateway_id: SQLite no aplica ON DELETE y los borrados de
grupos se resuelven de forma explícita — una regla cuyo grupo desaparece
simplemente no coincide con ningún nodo (degradación segura, nunca error).
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column("group_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_rules", "group_id")
