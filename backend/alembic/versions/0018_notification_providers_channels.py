"""Notificaciones multi-proveedor: separa proveedor (integración) de canal
lógico

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-15

`notification_channels` (Fase 3C: id/name/channel_type/config/enabled) se
renombra a `notification_providers` (instancia de proveedor configurada,
p.ej. "bot de Telegram del equipo"; columnas channel_type->provider,
config->configuration, +created_at/updated_at). `notification_channels` pasa
a ser un concepto NUEVO: el canal LÓGICO que las reglas conocen (p.ej.
"Operadores", "Guardia"), que agrupa 1+ proveedores vía
`notification_channel_providers`. `alert_rule_channels` permite que una
regla apunte a 0+ canales lógicos (N:M); sin canales asignados, el
dispatcher sigue haciendo el broadcast de siempre a todos los proveedores
enabled=True — compatibilidad sin cambio de comportamiento hasta que se
asignen canales explícitamente.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("notification_channels", "notification_providers")
    with op.batch_alter_table("notification_providers") as batch_op:
        batch_op.alter_column("channel_type", new_column_name="provider")
        batch_op.alter_column("config", new_column_name="configuration")
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
        )
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
        )

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "notification_channel_providers",
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("notification_channels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("notification_providers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "alert_rule_channels",
        sa.Column(
            "rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("notification_channels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("alert_rule_channels")
    op.drop_table("notification_channel_providers")
    op.drop_table("notification_channels")
    with op.batch_alter_table("notification_providers") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.alter_column("configuration", new_column_name="config")
        batch_op.alter_column("provider", new_column_name="channel_type")
    op.rename_table("notification_providers", "notification_channels")
