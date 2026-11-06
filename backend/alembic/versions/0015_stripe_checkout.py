"""TEST Checkout infrastructure; no backfill or commercial changes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stripe_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("payment_obligations.quote_id"),
            nullable=False,
        ),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("session_id", sa.String(200), unique=True),
        sa.Column("payment_intent_id", sa.String(200), unique=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("checkout_url", sa.String(2000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("return_origin", sa.String(500), nullable=False),
    )
    op.create_index("ix_stripe_attempts_quote_id", "stripe_attempts", ["quote_id"])
    op.create_index(
        "uq_stripe_active_attempt",
        "stripe_attempts",
        ["quote_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('expired', 'cancelled')"),
    )
    op.create_table(
        "stripe_evidence",
        sa.Column("event_id", sa.String(200), primary_key=True),
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("payment_obligations.quote_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("restricted", sa.Boolean(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_stripe_evidence_quote_id", "stripe_evidence", ["quote_id"])
    op.execute(
        "CREATE TRIGGER immutable_stripe_evidence BEFORE UPDATE OR DELETE ON stripe_evidence FOR EACH ROW EXECUTE FUNCTION spectra_immutable_pricing()"
    )
    op.execute("""CREATE FUNCTION stripe_attempt_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Stripe attempts cannot be deleted'; END IF;
      IF (NEW.id, NEW.quote_id, NEW.account_id, NEW.created_at, NEW.return_origin) IS DISTINCT FROM
         (OLD.id, OLD.quote_id, OLD.account_id, OLD.created_at, OLD.return_origin)
         OR (OLD.session_id IS NOT NULL AND NEW.session_id IS DISTINCT FROM OLD.session_id)
         OR (OLD.payment_intent_id IS NOT NULL AND NEW.payment_intent_id IS DISTINCT FROM OLD.payment_intent_id)
      THEN RAISE EXCEPTION 'Stripe attempt identity is immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER stripe_attempt_identity BEFORE UPDATE OR DELETE ON stripe_attempts FOR EACH ROW EXECUTE FUNCTION stripe_attempt_identity_guard()"
    )


def downgrade():
    for table in ("stripe_evidence", "stripe_attempts"):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})"))
            .scalar()
        ):
            raise RuntimeError("Refusing to remove financial history; recover forward")
    op.drop_table("stripe_evidence")
    op.drop_table("stripe_attempts")
    op.execute("DROP FUNCTION stripe_attempt_identity_guard()")
