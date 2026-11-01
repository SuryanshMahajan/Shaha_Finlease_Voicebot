"""Add import identifiers, birth year verification, and call outcomes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models import CallOutcome

revision = "0002_customer_workflow"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

call_outcome = postgresql.ENUM(
    *(outcome.value for outcome in CallOutcome),
    name="call_outcome",
    create_type=False,
)


def upgrade():
    if op.get_bind().dialect.name == "mssql":
        return
    op.add_column("customers", sa.Column("customer_ref", sa.String(64), nullable=True))
    op.add_column("customers", sa.Column("birth_year", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE customers "
        "SET customer_ref = 'LEGACY-' || upper(replace(id::text, '-', '')) "
        "WHERE customer_ref IS NULL"
    )
    op.alter_column("customers", "customer_ref", nullable=False)
    op.create_unique_constraint("uq_customers_customer_ref", "customers", ["customer_ref"])

    call_outcome.create(op.get_bind(), checkfirst=True)
    op.add_column("calls", sa.Column("outcome", call_outcome, nullable=True))


def downgrade():
    if op.get_bind().dialect.name == "mssql":
        return
    op.drop_column("calls", "outcome")
    call_outcome.drop(op.get_bind(), checkfirst=True)
    op.drop_constraint("uq_customers_customer_ref", "customers", type_="unique")
    op.drop_column("customers", "birth_year")
    op.drop_column("customers", "customer_ref")
