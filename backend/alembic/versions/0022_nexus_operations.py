"""JenTastic-Nexus: cola persistente de operaciones (ADR 0027 §4)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-29

Distinta de `admin_operations` (ADR 0013): el gateway nunca reporta un
resultado estructurado de vuelta — el firmware Nexus solo recibe texto y
responde por texto libre en la malla. Toda la correlación (reensamblado +
match comando↔respuesta) vive en memoria del proceso backend
(`application/nexus_operations.py`, reutiliza el núcleo puro de ADR 0027),
esta tabla solo persiste el estado observable: pendiente/enviado/
confirmado/sin respuesta.
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nexus_operations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gateway_id", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_value", sa.String(64), nullable=True),
        sa.Column("command_name", sa.String(32), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("text", sa.String(256), nullable=False),
        sa.Column("destructive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requires_save", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("busy_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_kind", sa.String(16), nullable=True),
        sa.Column("response_data", sa.JSON(), nullable=True),
    )
    op.create_index("ix_nexus_ops_status_created", "nexus_operations", ["status", "created_at"])
    op.create_index("ix_nexus_ops_gateway_status", "nexus_operations", ["gateway_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_nexus_ops_gateway_status", table_name="nexus_operations")
    op.drop_index("ix_nexus_ops_status_created", table_name="nexus_operations")
    op.drop_table("nexus_operations")
