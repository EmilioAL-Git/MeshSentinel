"""Chat: chat_messages — monitor de TEXT_MESSAGE_APP

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-14

Mismo paquete que ya narra Actividad 2.0 (`_on_message` en `ingest.py`),
persistido aparte con columnas estructuradas (channel_index, to_node_id) que
`activity_log` no ofrece indexadas — necesarias para el selector de
canales/DM del chat y como base de una futura fase de envío de mensajes sin
rehacer el esquema (direction/delivery_status/reply_to_id/actor_id
preparados y sin usar todavía).
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("from_node_id", sa.String(16), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("to_node_id", sa.String(16), nullable=True),
        sa.Column("channel_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("channel_name", sa.String(64), nullable=True),
        sa.Column("text", sa.String(512), nullable=False),
        sa.Column("gateway_id", sa.String(64), nullable=True),
        sa.Column("rssi", sa.Integer(), nullable=True),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("hops_away", sa.Integer(), nullable=True),
        sa.Column("hop_limit", sa.Integer(), nullable=True),
        sa.Column("hop_start", sa.Integer(), nullable=True),
        sa.Column("encrypted", sa.Boolean(), nullable=True),
        sa.Column("packet_id", sa.BigInteger(), nullable=True),
        sa.Column("direction", sa.String(8), nullable=False, server_default="inbound"),
        sa.Column("delivery_status", sa.String(16), nullable=True),
        sa.Column(
            "reply_to_id",
            sa.Integer(),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL", name="fk_chat_messages_reply_to_id"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL", name="fk_chat_messages_actor_id"),
            nullable=True,
        ),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_received_at", "chat_messages", ["received_at"])
    op.create_index(
        "ix_chat_messages_channel_received", "chat_messages", ["channel_index", "received_at"]
    )
    op.create_index(
        "ix_chat_messages_from_received", "chat_messages", ["from_node_id", "received_at"]
    )
    op.create_index("ix_chat_messages_to_received", "chat_messages", ["to_node_id", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_to_received", table_name="chat_messages")
    op.drop_index("ix_chat_messages_from_received", table_name="chat_messages")
    op.drop_index("ix_chat_messages_channel_received", table_name="chat_messages")
    op.drop_index("ix_chat_messages_received_at", table_name="chat_messages")
    op.drop_table("chat_messages")
