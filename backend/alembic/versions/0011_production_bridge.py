"""Explicit production registry ownership; no backfill of legacy identities."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE physical_cards ADD CONSTRAINT uq_pc_submission UNIQUE (id, submission_id)"
    )
    op.execute("""
        CREATE TABLE production_orders (
            submission_id UUID PRIMARY KEY REFERENCES customer_submissions(id),
            registry_id UUID NOT NULL,
            mode VARCHAR(8) NOT NULL CHECK (mode IN ('create','adopt')),
            local_order_id VARCHAR(40) CHECK (local_order_id ~ '^ORD-[0-9]{6,}$'),
            actor_id UUID NOT NULL REFERENCES customers(id),
            reason VARCHAR(1000) NOT NULL CHECK (length(trim(reason)) > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (registry_id,local_order_id), UNIQUE (submission_id,registry_id)
        );
        CREATE TABLE production_cards (
            physical_card_id UUID PRIMARY KEY,
            submission_id UUID NOT NULL,
            registry_id UUID NOT NULL,
            local_card_id VARCHAR(40) NOT NULL CHECK (local_card_id ~ '^SLB-C-[0-9]{6,}$'),
            FOREIGN KEY (submission_id,registry_id) REFERENCES production_orders(submission_id,registry_id),
            FOREIGN KEY (physical_card_id,submission_id) REFERENCES physical_cards(id,submission_id),
            UNIQUE (registry_id,local_card_id)
        );
        CREATE FUNCTION immutable_production_mapping() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Production mapping cannot be deleted'; END IF;
            IF TG_TABLE_NAME = 'production_cards' THEN
                RAISE EXCEPTION 'Production card mapping is immutable';
            END IF;
            IF NEW.submission_id IS DISTINCT FROM OLD.submission_id OR
               NEW.registry_id IS DISTINCT FROM OLD.registry_id OR
               NEW.mode IS DISTINCT FROM OLD.mode OR
               NEW.actor_id IS DISTINCT FROM OLD.actor_id OR
               NEW.reason IS DISTINCT FROM OLD.reason OR
               NEW.created_at IS DISTINCT FROM OLD.created_at OR
               (OLD.local_order_id IS NOT NULL AND NEW.local_order_id IS DISTINCT FROM OLD.local_order_id)
            THEN RAISE EXCEPTION 'Production mapping is immutable'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_production_order BEFORE UPDATE OR DELETE ON production_orders
            FOR EACH ROW EXECUTE FUNCTION immutable_production_mapping();
        CREATE TRIGGER immutable_production_card BEFORE UPDATE OR DELETE ON production_cards
            FOR EACH ROW EXECUTE FUNCTION immutable_production_mapping();
        CREATE FUNCTION production_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Production mapping history cannot be truncated'; END $$;
        CREATE TRIGGER production_orders_no_truncate BEFORE TRUNCATE ON production_orders
            FOR EACH STATEMENT EXECUTE FUNCTION production_no_truncate();
        CREATE TRIGGER production_cards_no_truncate BEFORE TRUNCATE ON production_cards
            FOR EACH STATEMENT EXECUTE FUNCTION production_no_truncate();
    """)


def downgrade():
    # Mapped identities must never be silently discarded by a rollback.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM production_orders) THEN
            RAISE EXCEPTION 'Restore a reviewed backup; production mappings exist';
        END IF;
    END $$""")
    op.drop_table("production_cards")
    op.drop_table("production_orders")
    op.execute("DROP FUNCTION immutable_production_mapping()")
    op.execute("DROP FUNCTION production_no_truncate()")
    op.drop_constraint("uq_pc_submission", "physical_cards", type_="unique")
