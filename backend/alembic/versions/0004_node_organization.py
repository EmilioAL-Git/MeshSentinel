"""Organización de nodos (M1.2): favoritos, ignorados, etiquetas y grupos

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("nodes", sa.Column("is_ignored", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("color", sa.String(16), nullable=True),
    )
    op.create_table(
        "node_tags",
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        # Preparado para el diseño completo del Módulo 1 (grupos dinámicos y
        # acciones masivas); en M1.2 solo se usan grupos estáticos manuales
        sa.Column("kind", sa.String(16), nullable=False, server_default="static"),
        sa.Column("filter_expr", sa.Text(), nullable=True),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", sa.String(16), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("node_tags")
    op.drop_table("tags")
    op.drop_column("nodes", "is_ignored")
    op.drop_column("nodes", "is_favorite")
