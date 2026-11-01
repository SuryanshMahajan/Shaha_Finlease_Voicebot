"""Use a filtered unique index so many calls may have no provider SID."""
from alembic import op
import sqlalchemy as sa

revision = "0008_provider_sid_index"
down_revision = "0007_assignment_language"
branch_labels = None
depends_on = None

INDEX = "uq_calls_provider_call_sid"
CONSTRAINT = "uq_calls_provider_call_sid"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        # SQLAlchemy's MSSQL dialect does not implement get_unique_constraints.
        # Drop either form of the old unique object before making the filtered index.
        bind.execute(sa.text(f"""
            IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = '{CONSTRAINT}' AND parent_object_id = OBJECT_ID('dbo.calls'))
                ALTER TABLE dbo.calls DROP CONSTRAINT [{CONSTRAINT}];
            IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{INDEX}' AND object_id = OBJECT_ID('dbo.calls'))
                DROP INDEX [{INDEX}] ON dbo.calls;
        """))
        bind.execute(sa.text(
            f"CREATE UNIQUE INDEX [{INDEX}] ON dbo.calls (provider_call_sid) WHERE provider_call_sid IS NOT NULL"
        ))
        return
    inspector = sa.inspect(bind)
    if any(item["name"] == CONSTRAINT for item in inspector.get_unique_constraints("calls")):
        op.drop_constraint(CONSTRAINT, "calls", type_="unique")
    if not any(item["name"] == INDEX for item in sa.inspect(bind).get_indexes("calls")):
        op.create_index(
            INDEX,
            "calls",
            ["provider_call_sid"],
            unique=True,
            postgresql_where=sa.text("provider_call_sid IS NOT NULL"),
            mssql_where=sa.text("provider_call_sid IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        bind.execute(sa.text(f"DROP INDEX [{INDEX}] ON dbo.calls"))
        bind.execute(sa.text(
            f"ALTER TABLE dbo.calls ADD CONSTRAINT [{CONSTRAINT}] UNIQUE (provider_call_sid)"
        ))
        return
    inspector = sa.inspect(bind)
    if any(item["name"] == INDEX for item in inspector.get_indexes("calls")):
        op.drop_index(INDEX, table_name="calls")
    if not any(item["name"] == CONSTRAINT for item in sa.inspect(bind).get_unique_constraints("calls")):
        op.create_unique_constraint(CONSTRAINT, "calls", ["provider_call_sid"])
