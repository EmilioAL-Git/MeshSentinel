"""Estados de verificación de SETs (M1.3): ampliar admin_operations.status

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "succeeded_unconfirmed" (21) no cabe en String(16)
    with op.batch_alter_table("admin_operations") as batch:
        batch.alter_column("status", type_=sa.String(32), existing_type=sa.String(16))


def downgrade() -> None:
    with op.batch_alter_table("admin_operations") as batch:
        batch.alter_column("status", type_=sa.String(16), existing_type=sa.String(32))
