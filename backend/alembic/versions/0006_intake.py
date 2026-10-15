"""W5.1 physical custody and staff authorization. Frozen PostgreSQL DDL."""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE staff_memberships (
            customer_id UUID NOT NULL,
            role VARCHAR(16) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (customer_id),
            CONSTRAINT ck_staff_role CHECK (role IN ('admin','operator')),
            FOREIGN KEY(customer_id) REFERENCES customers (id)
        )
    """)
    op.execute("""
        CREATE TABLE intake_audit_events (
            id UUID NOT NULL,
            submission_id UUID,
            actor_id UUID NOT NULL,
            action VARCHAR(64) NOT NULL,
            entity_id UUID NOT NULL,
            data JSONB NOT NULL,
            reason VARCHAR(2000),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(submission_id) REFERENCES customer_submissions (id),
            FOREIGN KEY(actor_id) REFERENCES customers (id)
        )
    """)
    op.execute('CREATE INDEX ix_intake_audit_events_submission_id ON intake_audit_events (submission_id)')
    op.execute("""
        CREATE TABLE intake_parcels (
            id UUID NOT NULL,
            reference VARCHAR(40) NOT NULL,
            submission_id UUID NOT NULL,
            received_by UUID NOT NULL,
            request_key UUID NOT NULL,
            request_data JSONB NOT NULL,
            carrier VARCHAR(100) NOT NULL,
            tracking VARCHAR(200) NOT NULL,
            notes VARCHAR(2000) NOT NULL,
            status VARCHAR(32) NOT NULL,
            received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (submission_id, request_key),
            CONSTRAINT ck_parcel_status CHECK (status IN ('received','reconciling','reconciled')),
            UNIQUE (reference),
            FOREIGN KEY(submission_id) REFERENCES customer_submissions (id),
            FOREIGN KEY(received_by) REFERENCES customers (id)
        )
    """)
    op.execute('CREATE INDEX ix_intake_parcels_submission_id ON intake_parcels (submission_id)')
    op.execute("""
        CREATE TABLE submission_intakes (
            submission_id UUID NOT NULL,
            status VARCHAR(32) NOT NULL,
            override_reason VARCHAR(1000),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (submission_id),
            CONSTRAINT ck_intake_status CHECK (status IN ('awaiting_receipt','partially_received','reconciliation_pending','reconciled','on_hold')),
            FOREIGN KEY(submission_id) REFERENCES customer_submissions (id)
        )
    """)
    op.execute("""
        CREATE TABLE physical_cards (
            id UUID NOT NULL,
            reference VARCHAR(40) NOT NULL,
            submission_id UUID NOT NULL,
            parcel_id UUID NOT NULL,
            entry_id UUID,
            grading_card_id UUID,
            received_by UUID NOT NULL,
            request_key UUID NOT NULL,
            request_data JSONB NOT NULL,
            status VARCHAR(32) NOT NULL,
            notes VARCHAR(2000) NOT NULL,
            received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (submission_id, request_key),
            CONSTRAINT ck_physical_status CHECK (status IN ('unidentified','matched','questionable')),
            UNIQUE (reference),
            FOREIGN KEY(submission_id) REFERENCES customer_submissions (id),
            FOREIGN KEY(parcel_id) REFERENCES intake_parcels (id),
            FOREIGN KEY(entry_id) REFERENCES customer_submission_entries (id),
            UNIQUE (grading_card_id),
            FOREIGN KEY(grading_card_id) REFERENCES cards (id),
            FOREIGN KEY(received_by) REFERENCES customers (id)
        )
    """)
    op.execute('CREATE INDEX ix_physical_cards_parcel_id ON physical_cards (parcel_id)')
    op.execute('CREATE INDEX ix_physical_cards_submission_id ON physical_cards (submission_id)')
    op.execute("""
        CREATE TABLE intake_discrepancies (
            id UUID NOT NULL,
            submission_id UUID NOT NULL,
            card_id UUID,
            entry_id UUID,
            kind VARCHAR(32) NOT NULL,
            quantity INTEGER NOT NULL,
            notes VARCHAR(2000) NOT NULL,
            status VARCHAR(16) NOT NULL,
            resolution VARCHAR(2000),
            created_by UUID NOT NULL,
            resolved_by UUID,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT ck_discrepancy_kind CHECK (kind IN ('missing','unexpected','mismatch','damaged','unresolved')),
            CONSTRAINT ck_discrepancy_status CHECK (status IN ('open','resolved','acknowledged')),
            CONSTRAINT ck_discrepancy_quantity CHECK (quantity BETWEEN 1 AND 10000),
            FOREIGN KEY(submission_id) REFERENCES customer_submissions (id),
            FOREIGN KEY(card_id) REFERENCES physical_cards (id),
            FOREIGN KEY(entry_id) REFERENCES customer_submission_entries (id),
            FOREIGN KEY(created_by) REFERENCES customers (id),
            FOREIGN KEY(resolved_by) REFERENCES customers (id)
        )
    """)
    op.execute('CREATE INDEX ix_intake_discrepancies_submission_id ON intake_discrepancies (submission_id)')
    op.execute("CREATE FUNCTION spectra_immutable_intake_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Operational audit history is immutable'; END $$")
    op.execute('CREATE TRIGGER immutable_intake_audit BEFORE UPDATE OR DELETE OR TRUNCATE ON intake_audit_events FOR EACH STATEMENT EXECUTE FUNCTION spectra_immutable_intake_audit()')


def downgrade():
    op.drop_table('intake_discrepancies')
    op.drop_table('physical_cards')
    op.drop_table('submission_intakes')
    op.drop_table('intake_parcels')
    op.drop_table('intake_audit_events')
    op.drop_table('staff_memberships')
    op.execute("DROP FUNCTION spectra_immutable_intake_audit()")
