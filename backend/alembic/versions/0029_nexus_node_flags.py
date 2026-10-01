"""Listas conocidas de favoritos/ignorados de nodos Nexus

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-01

nexus_node_flags: lo que cada nodo JenTastic-Nexus tiene como favorito/
ignorado, alimentado por las confirmaciones de FAV/UNFAV/IGNORE/UNIGNORE
y las lecturas FAVS/IGNORED.
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nexus_node_flags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(16), nullable=False),
        sa.Column("flag_type", sa.String(16), nullable=False),
        sa.Column("subject_node_id", sa.String(16), nullable=False),
        sa.Column("subject_short_name", sa.String(16), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("node_id", "flag_type", "subject_node_id", name="uq_nexus_node_flag"),
    )
    op.create_index("ix_nexus_node_flags_node", "nexus_node_flags", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_nexus_node_flags_node", table_name="nexus_node_flags")
    op.drop_table("nexus_node_flags")
