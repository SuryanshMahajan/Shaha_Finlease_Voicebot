"""Add browser voice session, latency, and durable DNC audit metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0009_browser_voice_safety"
down_revision = "0008_provider_sid_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("calls", sa.Column("channel", sa.String(24), nullable=True))
    if bind.dialect.name == "mssql":
        op.execute(sa.text(
            "UPDATE calls SET channel = CASE WHEN simulated = 1 THEN 'scripted_simulation' ELSE 'telephony' END WHERE channel IS NULL"
        ))
    else:
        op.execute(sa.text(
            "UPDATE calls SET channel = CASE WHEN simulated IS TRUE THEN 'scripted_simulation' ELSE 'telephony' END WHERE channel IS NULL"
        ))
    op.alter_column(
        "calls", "channel", existing_type=sa.String(24), nullable=False,
        server_default=sa.text("'scripted_simulation'"),
    )
    op.add_column("calls", sa.Column("voice_state", sa.String(16), server_default=sa.text("'new'"), nullable=False))
    op.add_column("calls", sa.Column("verification_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("calls", sa.Column("voice_verified", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("verification_events", sa.Column("call_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("verification_events", sa.Column("simulated", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_foreign_key(
        "fk_verification_events_call_id_calls", "verification_events", "calls",
        ["call_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "do_not_call_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.Uuid(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("action IN ('requested', 'released')", name="ck_do_not_call_events_action"),
    )
    op.create_index("ix_do_not_call_events_customer_created", "do_not_call_events", ["customer_id", "created_at"])

    op.create_table(
        "voice_turn_metrics",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("call_id", sa.Uuid(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("utterance_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recognition_completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("speech_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_latency_ms", sa.Integer(), nullable=False),
        sa.Column("recognition_latency_ms", sa.Integer(), nullable=False),
        sa.Column("server_processing_ms", sa.Integer(), nullable=False),
        sa.Column("synthesis_start_latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("call_id", "turn_id", name="uq_voice_turn_metrics_call_turn"),
    )
    op.create_index("ix_voice_turn_metrics_call_created", "voice_turn_metrics", ["call_id", "created_at"])

def downgrade() -> None:
    op.drop_index("ix_voice_turn_metrics_call_created", table_name="voice_turn_metrics")
    op.drop_table("voice_turn_metrics")
    op.drop_index("ix_do_not_call_events_customer_created", table_name="do_not_call_events")
    op.drop_table("do_not_call_events")
    op.drop_constraint("fk_verification_events_call_id_calls", "verification_events", type_="foreignkey")
    op.drop_column("verification_events", "simulated")
    op.drop_column("verification_events", "call_id")
    op.drop_column("calls", "voice_verified")
    op.drop_column("calls", "verification_attempts")
    op.drop_column("calls", "voice_state")
    op.drop_column("calls", "channel")
