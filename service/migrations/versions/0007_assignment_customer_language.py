"""Add assignment language fields and retain the PostgreSQL upgrade path."""
from alembic import op
import sqlalchemy as sa

revision = "0007_assignment_language"
down_revision = "0006_twilio_relay_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        # The SQL Server baseline creates current metadata in revision 0001.
        return
    op.add_column("customers", sa.Column("preferred_language", sa.String(2), nullable=False, server_default="en"))
    op.add_column("calls", sa.Column("language", sa.String(2), nullable=False, server_default="en"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        return
    op.drop_column("calls", "language")
    op.drop_column("customers", "preferred_language")
