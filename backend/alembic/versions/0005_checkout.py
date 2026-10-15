"""Delivery data and immutable shipping configurations; no commercial activation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("customer_addresses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.String(size), nullable=False) for name, size in (("recipient",200),("line1",200),("line2",200),("postal_code",32),("city",100),("country",2),("phone",32),("instructions",1000))],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1", name="ck_address_version"))
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])
    op.create_table("submission_deliveries",
        sa.Column("submission_id", sa.Uuid(), sa.ForeignKey("customer_submissions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("address_id", sa.Uuid(), sa.ForeignKey("customer_addresses.id")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("declared_value_minor", sa.Integer()),
        sa.Column("service_id", sa.String(64)),
        sa.Column("parcel", JSONB(), nullable=False),
        sa.CheckConstraint("version >= 1 AND (declared_value_minor IS NULL OR declared_value_minor >= 0)", name="ck_delivery_values"))
    op.create_index("ix_submission_deliveries_address_id", "submission_deliveries", ["address_id"])
    op.create_table("shipping_configurations",
        sa.Column("version", sa.Uuid(), primary_key=True),
        sa.Column("document", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("shipping_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("current_version", sa.Uuid(), sa.ForeignKey("shipping_configurations.version")),
        sa.CheckConstraint("id = 1", name="ck_shipping_singleton"))
    op.execute("INSERT INTO shipping_state (id) VALUES (1)")
    op.execute("CREATE TRIGGER immutable_pricing BEFORE UPDATE ON shipping_configurations FOR EACH ROW EXECUTE FUNCTION spectra_immutable_pricing()")


def downgrade():
    op.drop_table("shipping_state")
    op.drop_table("shipping_configurations")
    op.drop_table("submission_deliveries")
    op.drop_table("customer_addresses")
