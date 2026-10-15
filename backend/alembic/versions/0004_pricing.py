"""Versioned service catalogs, entry configurations, quotes and acceptance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customer_submissions", sa.Column("pricing_revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("customer_submission_entries", sa.Column("processing_tier", sa.String(64), nullable=False, server_default="standard"))
    op.add_column("customer_submission_entries", sa.Column("upgrade_ids", JSONB(), nullable=False, server_default=sa.text("'[\"classic\"]'::jsonb")))
    op.create_table("pricing_catalogs",
        sa.Column("version", sa.Uuid(), primary_key=True),
        sa.Column("document", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("pricing_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("current_version", sa.Uuid(), sa.ForeignKey("pricing_catalogs.version")),
        sa.CheckConstraint("id = 1", name="ck_pricing_state_singleton"))
    op.execute("INSERT INTO pricing_state (id) VALUES (1)")
    op.create_table("submission_quotes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("submission_id", sa.Uuid(), sa.ForeignKey("customer_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pricing_revision", sa.Integer(), nullable=False),
        sa.Column("catalog_version", sa.Uuid(), sa.ForeignKey("pricing_catalogs.version"), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="ck_quote_expiry"))
    op.create_index("ix_submission_quotes_submission_id", "submission_quotes", ["submission_id"])
    op.create_table("quote_acceptances",
        sa.Column("submission_id", sa.Uuid(), sa.ForeignKey("customer_submissions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("quote_id", sa.Uuid(), sa.ForeignKey("submission_quotes.id"), nullable=False, unique=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    # Catalog documents, prices and accepted terms cannot be rewritten in place.
    op.execute("""CREATE FUNCTION spectra_immutable_pricing() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Pricing snapshots are immutable'; END;
        $$ LANGUAGE plpgsql""")
    for table in ("pricing_catalogs", "submission_quotes", "quote_acceptances"):
        op.execute(f"CREATE TRIGGER immutable_pricing BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION spectra_immutable_pricing()")


def downgrade():
    op.drop_table("quote_acceptances")
    op.drop_table("submission_quotes")
    op.drop_table("pricing_state")
    op.drop_table("pricing_catalogs")
    op.execute("DROP FUNCTION spectra_immutable_pricing()")
    op.drop_column("customer_submission_entries", "upgrade_ids")
    op.drop_column("customer_submission_entries", "processing_tier")
    op.drop_column("customer_submissions", "pricing_revision")
