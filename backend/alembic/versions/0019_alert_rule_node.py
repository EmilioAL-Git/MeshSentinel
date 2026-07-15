"""Reglas por nodo individual: alert_rules.node_id

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-15

Amplía el escopado de reglas (0017, group_id) con un tercer nivel: vigilar
un nodo concreto en vez de toda la red o un grupo. Mutuamente excluyente
con group_id (validado en la API, no en BD). Sin ForeignKey, mismo criterio
que group_id/preferred_gateway_id: un nodo borrado deja la regla sin
coincidencias (degradación segura), nunca un error de integridad.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column("node_id", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_rules", "node_id")
