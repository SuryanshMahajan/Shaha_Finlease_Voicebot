"""Add callback follow-up history and outbound consent safeguards."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_callback_privacy"
down_revision = "0003_verification_events"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "mssql":
        return
    op.add_column("customers", sa.Column("outbound_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("customers", sa.Column("consent_source", sa.String(120), nullable=True))
    op.add_column("customers", sa.Column("do_not_call", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("calls", sa.Column("simulated", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("verification_events", sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_verification_events_customer_id", "verification_events", ["customer_id"])
    op.add_column("transcript_messages", sa.Column("provenance", sa.String(64), server_default="legacy_unknown", nullable=False))
    op.add_column("transcript_messages", sa.Column("language", sa.String(8), nullable=True))
    op.add_column("transcript_messages", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE transcript_messages SET expires_at = created_at + interval '180 days' WHERE expires_at IS NULL")
    op.alter_column("transcript_messages", "expires_at", nullable=False, server_default=sa.text("(now() + interval '180 days')"))
    op.create_index("ix_transcript_expires_at", "transcript_messages", ["expires_at"])

    op.create_table(
        "callback_followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'scheduled', 'completed', 'cancelled', 'missed')", name="ck_callback_followups_status"),
    )
    op.create_index("ix_callback_followups_scheduled_at", "callback_followups", ["scheduled_at"])
    op.create_index("uq_callback_followups_active_call", "callback_followups", ["call_id"], unique=True, postgresql_where=sa.text("status IN ('pending', 'scheduled')"))
    op.create_table(
        "callback_followup_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("followup_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("callback_followups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "call_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("provenance", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), server_default=sa.text("(now() + interval '180 days')"), nullable=False),
        sa.UniqueConstraint("call_id", name="uq_call_summaries_call_id"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_call_summaries_status"),
        sa.CheckConstraint("status != 'completed' OR (content IS NOT NULL AND provenance IS NOT NULL)", name="ck_call_summaries_completed_content"),
    )
    op.create_index("ix_call_summaries_expires_at", "call_summaries", ["expires_at"])


def downgrade():
    if op.get_bind().dialect.name == "mssql":
        return
    op.drop_index("ix_call_summaries_expires_at", table_name="call_summaries")
    op.drop_table("call_summaries")
    op.drop_table("callback_followup_events")
    op.drop_index("uq_callback_followups_active_call", table_name="callback_followups")
    op.drop_index("ix_callback_followups_scheduled_at", table_name="callback_followups")
    op.drop_table("callback_followups")
    op.drop_index("ix_transcript_expires_at", table_name="transcript_messages")
    op.drop_column("transcript_messages", "expires_at")
    op.drop_column("transcript_messages", "language")
    op.drop_column("transcript_messages", "provenance")
    op.drop_index("ix_verification_events_customer_id", table_name="verification_events")
    op.drop_column("verification_events", "customer_id")
    op.drop_column("calls", "simulated")
    op.drop_column("customers", "do_not_call")
    op.drop_column("customers", "consent_source")
    op.drop_column("customers", "outbound_consent_at")
