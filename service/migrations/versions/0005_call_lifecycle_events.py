"""Persist safe call lifecycle transitions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_call_lifecycle_events"
down_revision = "0004_callback_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        return
    op.create_table(
        "call_lifecycle_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_lifecycle_call_created", "call_lifecycle_events", ["call_id", "created_at"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        return
    op.drop_index("ix_call_lifecycle_call_created", table_name="call_lifecycle_events")
    op.drop_table("call_lifecycle_events")
