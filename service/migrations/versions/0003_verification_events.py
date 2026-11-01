"""Persist verification outcomes without factors or customer identifiers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_verification_events"
down_revision = "0002_customer_workflow"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "mssql":
        return
    op.create_table(
        "verification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_verification_events_created_at", "verification_events", ["created_at"])


def downgrade():
    if op.get_bind().dialect.name == "mssql":
        return
    op.drop_index("ix_verification_events_created_at", table_name="verification_events")
    op.drop_table("verification_events")
