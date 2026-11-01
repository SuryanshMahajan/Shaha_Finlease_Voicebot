"""Add provider call identifier and connected lifecycle state."""
from alembic import op
import sqlalchemy as sa

revision = "0006_twilio_relay_metadata"
down_revision = "0005_call_lifecycle_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        return
    op.execute("ALTER TYPE call_status ADD VALUE IF NOT EXISTS 'connected'")
    op.add_column("calls", sa.Column("provider_call_sid", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_calls_provider_call_sid", "calls", ["provider_call_sid"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        return
    op.drop_constraint("uq_calls_provider_call_sid", "calls", type_="unique")
    op.drop_column("calls", "provider_call_sid")
    # PostgreSQL does not support removing an enum value in place; retain the
    # unused 'connected' value so downgrade never rebuilds or rewrites calls.
