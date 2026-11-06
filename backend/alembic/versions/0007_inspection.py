"""W5.2a inspection dossiers, controlled custody and immutable image evidence.

Frozen PostgreSQL DDL; no existing operational rows are rewritten.
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE inspections (
        	id UUID NOT NULL, 
        	physical_card_id UUID NOT NULL, 
        	started_by UUID NOT NULL, 
        	status VARCHAR(20) NOT NULL, 
        	location VARCHAR(40) NOT NULL, 
        	version INTEGER NOT NULL, 
        	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
        	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
        	transitioned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
        	PRIMARY KEY (id), 
        	CONSTRAINT ck_inspection_status CHECK (status IN ('in_progress','paused')), 
        	CONSTRAINT ck_inspection_location CHECK ((status = 'in_progress' AND location = 'inspection_workstation') OR (status = 'paused' AND location = 'inspection_hold_storage')), 
        	CONSTRAINT ck_inspection_version CHECK (version > 0), 
        	UNIQUE (physical_card_id), 
        	FOREIGN KEY(physical_card_id) REFERENCES physical_cards (id), 
        	FOREIGN KEY(started_by) REFERENCES customers (id)
        )
    """)
    op.execute("""
        CREATE TABLE inspection_custody_events (
        	id UUID NOT NULL, 
        	inspection_id UUID NOT NULL, 
        	actor_id UUID NOT NULL, 
        	request_key UUID NOT NULL, 
        	action VARCHAR(16) NOT NULL, 
        	previous_state VARCHAR(20) NOT NULL, 
        	new_state VARCHAR(20) NOT NULL, 
        	source VARCHAR(40) NOT NULL, 
        	destination VARCHAR(40) NOT NULL, 
        	reason VARCHAR(1000) NOT NULL, 
        	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
        	PRIMARY KEY (id), 
        	UNIQUE (inspection_id, request_key), 
        	CONSTRAINT ck_custody_transition CHECK ((action = 'start' AND previous_state = 'not_started' AND new_state = 'in_progress' AND source = 'secure_intake_storage' AND destination = 'inspection_workstation') OR (action = 'pause' AND previous_state = 'in_progress' AND new_state = 'paused' AND source = 'inspection_workstation' AND destination = 'inspection_hold_storage') OR (action = 'resume' AND previous_state = 'paused' AND new_state = 'in_progress' AND source = 'inspection_hold_storage' AND destination = 'inspection_workstation')), 
        	FOREIGN KEY(inspection_id) REFERENCES inspections (id), 
        	FOREIGN KEY(actor_id) REFERENCES customers (id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_inspection_custody_events_inspection_id ON inspection_custody_events (inspection_id)
    """)
    op.execute("""
        CREATE INDEX ix_inspection_custody_history ON inspection_custody_events (inspection_id, created_at, id)
    """)
    op.execute("""
        CREATE TABLE inspection_images (
        	id UUID NOT NULL, 
        	inspection_id UUID NOT NULL, 
        	side VARCHAR(5) NOT NULL, 
        	version INTEGER NOT NULL, 
        	uploaded_by UUID NOT NULL, 
        	original_filename VARCHAR(255) NOT NULL, 
        	mime_type VARCHAR(32) NOT NULL, 
        	sha256 VARCHAR(64) NOT NULL, 
        	file_size INTEGER NOT NULL, 
        	storage_key VARCHAR(32) NOT NULL, 
        	reason VARCHAR(1000) NOT NULL, 
        	uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
        	PRIMARY KEY (id), 
        	UNIQUE (inspection_id, side, version), 
        	CONSTRAINT ck_inspection_image_side CHECK (side IN ('front','back')), 
        	CONSTRAINT ck_inspection_image_size CHECK (version > 0 AND file_size > 0), 
        	FOREIGN KEY(inspection_id) REFERENCES inspections (id), 
        	FOREIGN KEY(uploaded_by) REFERENCES customers (id), 
        	UNIQUE (storage_key)
        )
    """)
    op.execute("""
        CREATE INDEX ix_inspection_images_inspection_id ON inspection_images (inspection_id)
    """)
    op.execute("""
        CREATE TRIGGER immutable_inspection_custody_events BEFORE UPDATE OR DELETE OR TRUNCATE ON inspection_custody_events FOR EACH STATEMENT EXECUTE FUNCTION spectra_immutable_intake_audit()
    """)
    op.execute("""
        CREATE TRIGGER immutable_inspection_images BEFORE UPDATE OR DELETE OR TRUNCATE ON inspection_images FOR EACH STATEMENT EXECUTE FUNCTION spectra_immutable_intake_audit()
    """)


def downgrade():
    op.drop_table("inspection_images")
    op.drop_table("inspection_custody_events")
    op.drop_table("inspections")
