"""Register cards and preserve original image metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("game", sa.String(32), nullable=False),
        sa.Column("card_name", sa.String(200), nullable=False),
        sa.Column("set_name", sa.String(200), nullable=False),
        sa.Column("collector_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("game IN ('pokemon')", name="ck_cards_game"),
        sa.CheckConstraint("status IN ('registered')", name="ck_cards_status"),
    )
    op.create_table(
        "card_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("card_id", sa.Uuid(), sa.ForeignKey("cards.id"), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(32), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(32), nullable=False, unique=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("card_id", "side", name="uq_card_images_card_side"),
        sa.CheckConstraint("side IN ('front', 'back')", name="ck_card_images_side"),
        sa.CheckConstraint("file_size > 0", name="ck_card_images_size"),
    )
    op.create_index("ix_card_images_card_id", "card_images", ["card_id"])


def downgrade():
    op.drop_table("card_images")
    op.drop_table("cards")
