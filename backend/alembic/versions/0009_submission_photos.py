"""Optional per-declared-copy customer photographs; no historical row rewrites."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = depends_on = None


def upgrade():
    op.create_table('customer_submission_photos',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('entry_id', sa.Uuid(), sa.ForeignKey('customer_submission_entries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('copy_number', sa.Integer(), nullable=False),
        sa.Column('side', sa.String(5), nullable=False),
        sa.Column('uploaded_by', sa.Uuid(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('removed_at', sa.DateTime(timezone=True)),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(32), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('storage_key', sa.String(32), nullable=False, unique=True),
        sa.CheckConstraint("side IN ('front', 'back')", name='ck_submission_photo_side'),
        sa.CheckConstraint('copy_number BETWEEN 1 AND 100', name='ck_submission_photo_copy'),
        sa.CheckConstraint('file_size > 0', name='ck_submission_photo_size'))
    op.create_index('ix_customer_submission_photos_entry_id', 'customer_submission_photos', ['entry_id'])
    op.create_index('uq_submission_photo_active_slot', 'customer_submission_photos', ['entry_id', 'copy_number', 'side'],
                    unique=True, postgresql_where=sa.text('removed_at IS NULL'))


def downgrade():
    op.drop_table('customer_submission_photos')
