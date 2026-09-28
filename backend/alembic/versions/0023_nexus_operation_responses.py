"""JenTastic-Nexus: respuestas individuales de operaciones broadcast/group (ADR 0027 §11)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-29

Pedido explícito del usuario: al mandar un comando por difusión a la malla
Nexus, quiere ver a CADA nodo responder por separado, no un único estado
agregado. `nexus_operations.response_*` (0022) sigue siendo el único-y-
terminal para destinos dirigidos (local/node/mac) — esta tabla es
append-only y solo se usa para operaciones de destino múltiple
(broadcast/group), donde puede haber N respuestas de N nodos distintos.
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nexus_operation_responses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("nexus_operations.id"), nullable=False),
        sa.Column("from_node_id", sa.String(16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("response_kind", sa.String(16), nullable=False),
        sa.Column("response_data", sa.JSON(), nullable=True),
    )
    op.create_index("ix_nexus_op_responses_operation", "nexus_operation_responses", ["operation_id"])


def downgrade() -> None:
    op.drop_index("ix_nexus_op_responses_operation", table_name="nexus_operation_responses")
    op.drop_table("nexus_operation_responses")
