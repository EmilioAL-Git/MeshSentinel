"""Autenticación de MeshSentinel: auth_users, auth_sessions, auth_login_log

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-14

Aditiva y compatible: mientras auth_users no tenga ningún usuario is_admin
habilitado, la aplicación sigue funcionando exactamente igual que hoy (modo
abierto). admin_operations/admin_batches ganan actor_type/actor_id/
actor_username/actor_display_name — created_by se conserva como legado
(resolve_actor_label cae ahí si no hay actor todavía).
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_users_username", "auth_users", ["username"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
    )
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "auth_login_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_login_log_created", "auth_login_log", ["created_at"])

    # batch_alter_table (recreate="auto"): en SQLite, añadir una columna con
    # ForeignKey a una tabla EXISTENTE exige el modo de recreación por copia
    # (SQLite no soporta ALTER ... ADD CONSTRAINT); en PostgreSQL hace el
    # ALTER TABLE directo de siempre — mismo resultado en ambos motores.
    for table in ("admin_operations", "admin_batches"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("actor_type", sa.String(16), nullable=False, server_default="system")
            )
            batch_op.add_column(
                sa.Column(
                    "actor_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "auth_users.id", ondelete="SET NULL", name=f"fk_{table}_actor_id_auth_users"
                    ),
                    nullable=True,
                )
            )
            batch_op.add_column(sa.Column("actor_username", sa.String(64), nullable=True))
            batch_op.add_column(sa.Column("actor_display_name", sa.String(64), nullable=True))


def downgrade() -> None:
    for table in ("admin_operations", "admin_batches"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("actor_display_name")
            batch_op.drop_column("actor_username")
            batch_op.drop_column("actor_id")
            batch_op.drop_column("actor_type")

    op.drop_index("ix_auth_login_log_created", table_name="auth_login_log")
    op.drop_table("auth_login_log")

    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_auth_users_username", table_name="auth_users")
    op.drop_table("auth_users")
