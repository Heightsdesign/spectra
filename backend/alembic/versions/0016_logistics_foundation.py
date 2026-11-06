"""Additive C1 catalogs and selections; no rates, labels or financial changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('logistics_catalogs',
                    sa.Column('version', sa.Uuid(), primary_key=True),
                    sa.Column('document', postgresql.JSONB(), nullable=False),
                    sa.Column('sha256', sa.String(64), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('logistics_catalog_publications',
                    sa.Column('id', sa.Uuid(), primary_key=True),
                    sa.Column('catalog_version', sa.Uuid(), sa.ForeignKey('logistics_catalogs.version'), nullable=False),
                    sa.Column('sequence', sa.Integer(), nullable=False),
                    sa.Column('status', sa.String(32), nullable=False),
                    sa.Column('actor_reference', sa.String(500), nullable=False),
                    sa.Column('reason', sa.String(1000), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.UniqueConstraint('catalog_version', 'sequence'),
                    sa.CheckConstraint("status IN ('validated','published_test','withdrawn')", name='ck_logistics_publication_status'),
                    sa.CheckConstraint('sequence > 0', name='ck_logistics_publication_sequence'))
    op.create_index('ix_logistics_catalog_publications_catalog_version', 'logistics_catalog_publications', ['catalog_version'])
    op.create_table('logistics_state',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('current_version', sa.Uuid(), sa.ForeignKey('logistics_catalogs.version')),
                    sa.CheckConstraint('id = 1', name='ck_logistics_state_singleton'))
    op.execute('INSERT INTO logistics_state(id) VALUES (1)')
    op.create_table('submission_logistics_selections',
                    sa.Column('id', sa.Uuid(), primary_key=True),
                    sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('customer_submissions.id'), nullable=False),
                    sa.Column('version', sa.Integer(), nullable=False),
                    sa.Column('catalog_version', sa.Uuid(), sa.ForeignKey('logistics_catalogs.version')),
                    sa.Column('document', postgresql.JSONB(), nullable=False),
                    sa.Column('sha256', sa.String(64), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.UniqueConstraint('submission_id', 'version'),
                    sa.CheckConstraint('version > 0', name='ck_logistics_selection_version'))
    op.create_index('ix_submission_logistics_selections_submission_id', 'submission_logistics_selections', ['submission_id'])
    op.execute("""CREATE FUNCTION logistics_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Logistics history is immutable'; END $$""")
    for table in ('logistics_catalogs', 'logistics_catalog_publications', 'submission_logistics_selections'):
        op.execute(f'CREATE TRIGGER immutable_logistics BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION logistics_immutable()')
    op.execute("""CREATE FUNCTION logistics_selection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE last_version integer;
    BEGIN
      PERFORM id FROM customer_submissions WHERE id = NEW.submission_id FOR UPDATE;
      IF EXISTS (SELECT 1 FROM quote_acceptances WHERE submission_id = NEW.submission_id)
      THEN RAISE EXCEPTION 'Accepted logistics cannot be changed'; END IF;
      SELECT COALESCE(MAX(version),0) INTO last_version FROM submission_logistics_selections WHERE submission_id = NEW.submission_id;
      IF NEW.version <> last_version + 1 THEN RAISE EXCEPTION 'Logistics version conflict'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER guard_logistics_selection BEFORE INSERT ON submission_logistics_selections FOR EACH ROW EXECUTE FUNCTION logistics_selection_guard()')


def downgrade():
    # Preserve audit even for catalogs that were never published. No DROP path.
    raise RuntimeError('C1 history requires an approved archive procedure; destructive downgrade refused')
