"""Exact money limits and a timezone-independent calendar deadline constraint."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("payment_obligations", "verified_payments"):
        op.alter_column(
            table, "amount_minor", type_=sa.BigInteger(), existing_type=sa.Integer()
        )
    op.drop_constraint("ck_dispatch_30_days", "dispatch_expectations", type_="check")
    op.create_check_constraint(
        "ck_dispatch_30_days",
        "dispatch_expectations",
        "dispatch_deadline = ((verified_payment_at AT TIME ZONE 'UTC') + interval '30 days') AT TIME ZONE 'UTC'",
    )


def downgrade():
    op.drop_constraint("ck_dispatch_30_days", "dispatch_expectations", type_="check")
    op.create_check_constraint(
        "ck_dispatch_30_days",
        "dispatch_expectations",
        "dispatch_deadline = verified_payment_at + interval '30 days'",
    )
    for table in ("verified_payments", "payment_obligations"):
        op.alter_column(
            table, "amount_minor", type_=sa.Integer(), existing_type=sa.BigInteger()
        )
