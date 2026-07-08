"""Motor de alertas: alert_rules, alerts, notification_channels

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_rules_rule_type", "alert_rules", ["rule_type"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id"), nullable=False),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("correlation_key", sa.String(128), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_subject_id", "alerts", ["subject_id"])
    op.create_index("ix_alerts_correlation_key", "alerts", ["correlation_key"])
    op.create_index("ix_alerts_status_fired", "alerts", ["status", "fired_at"])

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("channel_type", sa.String(32), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("notification_channels")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
