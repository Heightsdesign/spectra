"""Independent customer copies; no backfill or confirmed snapshot rewrites."""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "customer_card_copies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False
        ),
        sa.Column("catalog_card_id", sa.Uuid(), sa.ForeignKey("tcg_cards.id")),
        *[
            sa.Column(name, sa.String(size), nullable=False)
            for name, size in [
                ("game", 64),
                ("card_name", 200),
                ("expansion", 200),
                ("card_number", 64),
                ("language", 64),
                ("notes", 2000),
            ]
        ],
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("version >= 1", name="ck_copy_version"),
    )
    op.create_index(
        "ix_customer_card_copies_customer_id", "customer_card_copies", ["customer_id"]
    )
    op.create_table(
        "customer_copy_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "copy_id",
            sa.Uuid(),
            sa.ForeignKey("customer_card_copies.id"),
            nullable=False,
        ),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("customer_submissions.id"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            sa.Uuid(),
            sa.ForeignKey("customer_submission_entries.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("released_by", sa.Uuid(), sa.ForeignKey("customers.id")),
        sa.Column("release_reason", sa.String(1000)),
        sa.CheckConstraint(
            "released_at IS NOT NULL OR entry_id IS NOT NULL",
            name="ck_copy_active_entry",
        ),
    )
    op.create_index(
        "ix_customer_copy_assignments_copy_id", "customer_copy_assignments", ["copy_id"]
    )
    op.create_index(
        "ix_customer_copy_assignments_submission_id",
        "customer_copy_assignments",
        ["submission_id"],
    )
    op.create_index(
        "uq_copy_active_assignment",
        "customer_copy_assignments",
        ["copy_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.add_column(
        "customer_submission_photos",
        sa.Column(
            "customer_copy_id", sa.Uuid(), sa.ForeignKey("customer_card_copies.id")
        ),
    )
    op.alter_column("customer_submission_photos", "entry_id", nullable=True)
    op.create_check_constraint(
        "ck_photo_parent",
        "customer_submission_photos",
        "(entry_id IS NOT NULL)::int + (customer_copy_id IS NOT NULL)::int = 1",
    )
    op.create_index(
        "uq_library_photo_slot",
        "customer_submission_photos",
        ["customer_copy_id", "side"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL AND customer_copy_id IS NOT NULL"),
    )


def downgrade():
    # Do not silently delete customer library data or immutable photo history.
    raise RuntimeError(
        "Library migration downgrade requires an explicit data-preservation plan."
    )
