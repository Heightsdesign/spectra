"""Append-only erroneous-registration voids; no physical-card backfill or rewrite."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE physical_card_voids (
            physical_card_id UUID PRIMARY KEY REFERENCES physical_cards(id),
            actor_id UUID NOT NULL REFERENCES customers(id),
            reason VARCHAR(1000) NOT NULL CHECK (length(trim(reason)) > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TRIGGER immutable_physical_card_voids BEFORE UPDATE OR DELETE OR TRUNCATE
            ON physical_card_voids FOR EACH STATEMENT EXECUTE FUNCTION spectra_immutable_intake_audit();
    """)


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM physical_card_voids) THEN
            RAISE EXCEPTION 'Void history exists; restore a reviewed backup instead';
        END IF;
    END $$""")
    op.drop_table("physical_card_voids")
