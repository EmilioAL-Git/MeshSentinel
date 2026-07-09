"""M5: gestión de gateways — extiende `gateways` con configuración persistente

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        # Identidad visible en la UI (ADR 0021 §2); managed=false = fila nacida
        # solo de un heartbeat, sin configurar todavía desde la aplicación.
        batch_op.add_column(sa.Column("name", sa.String(128), nullable=True))
        batch_op.add_column(
            sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("transport_type", sa.String(16), nullable=True))
        batch_op.add_column(
            sa.Column("connection_params", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        # Reservado para autoselección en Multi-Gateway (fase futura), sin lógica aún
        batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column(
                "desired_status", sa.String(16), nullable=False, server_default="disconnected"
            )
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        # Historial mínimo (no una tabla de eventos, pedido explícito del usuario)
        batch_op.add_column(sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_disconnected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))
        # Caché no durable del nodo local, refrescada en cada conexión (M5)
        batch_op.add_column(sa.Column("local_short_name", sa.String(8), nullable=True))
        batch_op.add_column(sa.Column("local_long_name", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("local_hw_model", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("local_firmware_version", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("gateways") as batch_op:
        for col in (
            "local_firmware_version",
            "local_hw_model",
            "local_long_name",
            "local_short_name",
            "last_error_at",
            "last_error",
            "last_disconnected_at",
            "last_connected_at",
            "deleted_at",
            "desired_status",
            "priority",
            "enabled",
            "connection_params",
            "transport_type",
            "managed",
            "name",
        ):
            batch_op.drop_column(col)
