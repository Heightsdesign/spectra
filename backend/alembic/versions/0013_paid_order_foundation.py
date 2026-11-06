"""Paid-order foundations. No historical paid-state backfill or identity allocation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "submission_quotes", sa.Column("physical_card_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_supplement_quote_pc",
        "submission_quotes",
        "physical_cards",
        ["physical_card_id", "submission_id"],
        ["id", "submission_id"],
    )
    # No data is manufactured: obligations are created only at new acceptance.
    op.create_table(
        "payment_obligations",
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("submission_quotes.id"),
            primary_key=True,
        ),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("customer_submissions.id"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "amount_minor >= 0 AND currency = 'EUR'", name="ck_payment_amount"
        ),
    )
    op.create_index(
        "ix_payment_obligations_submission_id", "payment_obligations", ["submission_id"]
    )
    op.create_table(
        "verified_payments",
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("payment_obligations.quote_id"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(200), nullable=False),
        sa.Column("provider_payment_id", sa.String(200), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("provider", "provider_event_id"),
        sa.UniqueConstraint("provider", "provider_payment_id"),
        sa.CheckConstraint(
            "amount_minor >= 0 AND currency = 'EUR'", name="ck_verified_amount"
        ),
    )
    op.create_table(
        "supplementary_acceptances",
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("submission_quotes.id"),
            primary_key=True,
        ),
        sa.Column(
            "physical_card_id",
            sa.Uuid(),
            sa.ForeignKey("physical_cards.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "commercial_entitlement_assignments",
        sa.Column(
            "physical_card_id",
            sa.Uuid(),
            sa.ForeignKey("physical_cards.id"),
            primary_key=True,
        ),
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("payment_obligations.quote_id"),
            nullable=False,
        ),
        sa.Column("card_key", sa.String(80), nullable=False),
        sa.Column("service_id", sa.String(64), nullable=False),
        sa.Column(
            "assigned_by", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("quote_id", "card_key"),
    )
    op.create_table(
        "dispatch_expectations",
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("customer_submissions.id"),
            primary_key=True,
        ),
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("verified_payments.quote_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("verified_payment_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy", JSONB(), nullable=False),
        sa.CheckConstraint(
            "dispatch_deadline = verified_payment_at + interval '30 days'",
            name="ck_dispatch_30_days",
        ),
    )
    op.create_table(
        "customer_shipment_declarations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("customer_submissions.id"),
            nullable=False,
        ),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column(
            "declared_by", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False
        ),
        sa.Column("declared_dispatch_at", sa.DateTime(timezone=True)),
        sa.Column("carrier", sa.String(100), nullable=False),
        sa.Column("tracking", sa.String(200), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("submission_id", "request_key"),
    )
    op.create_index(
        "ix_customer_shipment_declarations_submission_id",
        "customer_shipment_declarations",
        ["submission_id"],
    )
    op.create_table(
        "order_commercial_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("customer_submissions.id"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("customers.id")),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("reason", sa.String(2000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_order_commercial_events_submission_id",
        "order_commercial_events",
        ["submission_id"],
    )
    for table in (
        "payment_obligations",
        "verified_payments",
        "supplementary_acceptances",
        "commercial_entitlement_assignments",
        "dispatch_expectations",
        "customer_shipment_declarations",
        "order_commercial_events",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_commercial BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION spectra_immutable_pricing()"
        )


def downgrade():
    connection = op.get_bind()
    for table in (
        "order_commercial_events",
        "customer_shipment_declarations",
        "dispatch_expectations",
        "commercial_entitlement_assignments",
        "supplementary_acceptances",
        "verified_payments",
        "payment_obligations",
    ):
        if connection.execute(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")
        ).scalar():
            raise RuntimeError(
                "Refusing to remove immutable commercial history; use an approved recovery/archive procedure"
            )
    for table in (
        "order_commercial_events",
        "customer_shipment_declarations",
        "dispatch_expectations",
        "commercial_entitlement_assignments",
        "supplementary_acceptances",
        "verified_payments",
        "payment_obligations",
    ):
        op.drop_table(table)
    op.drop_constraint(
        "fk_supplement_quote_pc", "submission_quotes", type_="foreignkey"
    )
    op.drop_column("submission_quotes", "physical_card_id")
