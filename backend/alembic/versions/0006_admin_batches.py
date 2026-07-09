"""Batch Engine (M2): admin_batches + batch_id en admin_operations

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        # Snapshot congelado del alcance (auditoría: el filtro puede dar otro
        # resultado mañana) + descripción de cómo se seleccionó
        sa.Column("node_ids", sa.JSON(), nullable=False),
        sa.Column("scope_description", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),  # running|paused|cancelled|completed|completed_with_errors
        sa.Column("created_by", sa.String(64), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_batches_status", "admin_batches", ["status"])
    op.create_index("ix_admin_batches_created", "admin_batches", ["created_at"])

    # batch mode: SQLite no soporta ALTER con constraint FK inline
    with op.batch_alter_table("admin_operations") as batch:
        batch.add_column(sa.Column("batch_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_admin_operations_batch_id", "admin_batches", ["batch_id"], ["id"]
        )
    op.create_index("ix_admin_ops_batch", "admin_operations", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_ops_batch", table_name="admin_operations")
    with op.batch_alter_table("admin_operations") as batch:
        batch.drop_constraint("fk_admin_operations_batch_id", type_="foreignkey")
        batch.drop_column("batch_id")
    op.drop_table("admin_batches")
