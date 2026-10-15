"""Customer accounts, hashed sessions, single-use tokens and rate limits."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("preferred_language", sa.String(2), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email = lower(email)", name="ck_customers_email_normalized"),
        sa.CheckConstraint("preferred_language IN ('FR','EN')", name="ck_customers_language"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_customers_status"))
    for name, extra in [
        ("customer_sessions", [sa.Column("revoked_at", sa.DateTime(timezone=True))]),
        ("customer_auth_tokens", [sa.Column("purpose", sa.String(8), nullable=False), sa.Column("used_at", sa.DateTime(timezone=True)), sa.CheckConstraint("purpose IN ('verify','reset')", name="ck_customer_tokens_purpose")]),
    ]:
        op.create_table(name,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), *extra)
        op.create_index(f"ix_{name}_customer_id", name, ["customer_id"])
        op.create_index(f"ix_{name}_expires_at", name, ["expires_at"])
    op.create_table("auth_rate_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auth_rate_buckets_expires_at", "auth_rate_buckets", ["expires_at"])


def downgrade():
    op.drop_table("auth_rate_buckets")
    op.drop_table("customer_auth_tokens")
    op.drop_table("customer_sessions")
    op.drop_table("customers")
