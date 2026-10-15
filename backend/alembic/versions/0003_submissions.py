"""Customer submissions, independent of grading records."""
from alembic import op
import sqlalchemy as sa
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('customer_submissions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('reference', sa.String(40), nullable=False, unique=True),
        sa.Column('customer_id', sa.Uuid(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('notes', sa.String(2000), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint('version >= 1', name='ck_submission_version'))
    op.create_index('ix_customer_submissions_customer_id', 'customer_submissions', ['customer_id'])
    op.create_table('customer_submission_entries',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('customer_submissions.id', ondelete='CASCADE'), nullable=False),
        *[sa.Column(name, sa.String(length), nullable=False) for name, length in [('game',64), ('card_name',200), ('expansion',200), ('card_number',64), ('language',64), ('notes',2000)]],
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('quantity BETWEEN 1 AND 100', name='ck_entry_quantity'))
    op.create_index('ix_customer_submission_entries_submission_id', 'customer_submission_entries', ['submission_id'])

def downgrade():
    op.drop_table('customer_submission_entries')
    op.drop_table('customer_submissions')
