"""Persist partial verification and make browser turns retry-safe."""
from alembic import op
import sqlalchemy as sa

revision = "0010_voice_turn_idempotency"
down_revision = "0009_browser_voice_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("verification_name_match", sa.Boolean(), nullable=True))
    op.add_column("calls", sa.Column("verification_year_match", sa.Boolean(), nullable=True))
    op.add_column("callback_followups", sa.Column("timezone_name", sa.String(64), nullable=True))
    op.add_column("callback_followups", sa.Column("reason", sa.String(250), nullable=True))
    op.create_table(
        "voice_turn_requests",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("call_id", sa.Uuid(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("ended", sa.Boolean(), nullable=False),
        sa.Column("verification_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("call_id", "turn_id", name="uq_voice_turn_requests_call_turn"),
    )


def downgrade() -> None:
    op.drop_table("voice_turn_requests")
    op.drop_column("callback_followups", "reason")
    op.drop_column("callback_followups", "timezone_name")
    op.drop_column("calls", "verification_year_match")
    op.drop_column("calls", "verification_name_match")
