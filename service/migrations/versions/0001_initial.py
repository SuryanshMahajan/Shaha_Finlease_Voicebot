"""Initial customers, calls, and transcript schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.base import Base
from app.models import CallStatus  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

call_status = postgresql.ENUM(
    *(status.value for status in CallStatus),
    name="call_status",
    create_type=False,
)


def upgrade():
    if op.get_bind().dialect.name == "mssql":
        # The assignment SQL Server starts from the complete current metadata;
        # later historical PostgreSQL revisions are no-ops for this dialect.
        Base.metadata.create_all(bind=op.get_bind())
        return
    op.create_table("customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("phone_last4", sa.String(4)),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    call_status.create(op.get_bind(), checkfirst=True)
    op.create_table("calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL")),
        sa.Column("status", call_status, nullable=False), sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("callback_requested", sa.Boolean(), nullable=False))
    op.create_index("ix_calls_started_at", "calls", ["started_at"])
    op.create_index("ix_calls_status", "calls", ["status"])
    op.create_table("transcript_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaker", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_transcript_call_created", "transcript_messages", ["call_id", "created_at"])


def downgrade():
    if op.get_bind().dialect.name == "mssql":
        Base.metadata.drop_all(bind=op.get_bind())
        return
    op.drop_index("ix_transcript_call_created", table_name="transcript_messages")
    op.drop_table("transcript_messages")
    op.drop_index("ix_calls_status", table_name="calls")
    op.drop_index("ix_calls_started_at", table_name="calls")
    op.drop_table("calls")
    call_status.drop(op.get_bind(), checkfirst=True)
    op.drop_table("customers")

