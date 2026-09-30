"""gateways.container_managed: ciclo de vida del contenedor gestionado por el lanzador

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-30

ADR 0028: distingue una pasarela cuyo contenedor Docker crea/destruye la
aplicación (a través de gateway-launcher) de una externa (proceso nativo,
`.env`, despliegue manual) — orthogonal a `managed` (M5, "configurado desde
la app"). Default false: ninguna fila previa a este ADR fue creada por un
lanzador.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.add_column(
            sa.Column("container_managed", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.drop_column("container_managed")
