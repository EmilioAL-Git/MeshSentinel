"""Roles de usuario, favoritos personales y grupo personal (ADR 0029)

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-01

- auth_users.role (admin|manager|user): admin = is_admin previo; el resto de
  usuarios existentes pasan a `manager` (decisión del usuario: conservan su
  poder actual salvo usuarios y ajustes de gateways).
- user_favorites: favoritos por cuenta. Los `nodes.is_favorite` globales se
  copian como favoritos de cada usuario existente y se limpian (todo pasa a
  personal).
- groups.owner_user_id (único): grupo personal, uno por usuario.
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_users", sa.Column("role", sa.String(16), nullable=False, server_default="manager"))
    op.execute("UPDATE auth_users SET role = 'admin' WHERE is_admin = true")
    op.create_table(
        "user_favorites",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("auth_users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
    )
    op.execute(
        "INSERT INTO user_favorites (user_id, node_id) "
        "SELECT u.id, n.id FROM auth_users u CROSS JOIN nodes n WHERE n.is_favorite = true"
    )
    op.execute("UPDATE nodes SET is_favorite = false")
    with op.batch_alter_table("groups") as batch:
        batch.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_groups_owner_user", "auth_users", ["owner_user_id"], ["id"], ondelete="CASCADE")
        batch.create_unique_constraint("uq_groups_owner_user", ["owner_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("groups") as batch:
        batch.drop_constraint("uq_groups_owner_user", type_="unique")
        batch.drop_constraint("fk_groups_owner_user", type_="foreignkey")
        batch.drop_column("owner_user_id")
    op.drop_table("user_favorites")
    op.drop_column("auth_users", "role")
