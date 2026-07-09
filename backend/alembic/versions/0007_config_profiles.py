"""M3 Configuration Profiles: config_profiles + config_profile_versions

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "config_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Versiones inmutables (append-only): editar un perfil = nueva versión.
    # El contenido es {section: {field: value}} validado contra el esquema
    # protobuf introspeccionado (M1.4); solo campos gestionados por el perfil.
    op.create_table(
        "config_profile_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("config_profiles.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("comment", sa.String(256), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_id", "version", name="uq_profile_version"),
    )
    op.create_index(
        "ix_config_profile_versions_profile_id", "config_profile_versions", ["profile_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_config_profile_versions_profile_id", table_name="config_profile_versions")
    op.drop_table("config_profile_versions")
    op.drop_table("config_profiles")
