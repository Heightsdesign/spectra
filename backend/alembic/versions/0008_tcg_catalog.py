"""Optional catalog references; existing declaration strings remain snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = depends_on = None


def upgrade():
    op.create_table('tcg_games', sa.Column('id', sa.String(64), primary_key=True), sa.Column('name', sa.String(200), nullable=False))
    for key, name in [('pokemon', 'Pokémon'), ('one-piece', 'One Piece'), ('dragon-ball', 'Dragon Ball'), ('naruto', 'Naruto')]:
        op.execute(sa.text('INSERT INTO tcg_games (id, name) VALUES (:id, :name)').bindparams(id=key, name=name))
    op.create_table('tcg_expansions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('game', sa.String(64), sa.ForeignKey('tcg_games.id'), nullable=False),
        sa.Column('provider', sa.String(64), nullable=False), sa.Column('external_id', sa.String(200), nullable=False),
        sa.Column('language', sa.String(64), nullable=False), sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(200), nullable=False), sa.Column('release_year', sa.Integer()),
        sa.UniqueConstraint('provider', 'external_id', 'language'))
    op.create_index('ix_tcg_expansions_game', 'tcg_expansions', ['game'])
    op.create_table('tcg_cards', sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('expansion_id', sa.Uuid(), sa.ForeignKey('tcg_expansions.id'), nullable=False),
        sa.Column('provider', sa.String(64), nullable=False), sa.Column('external_id', sa.String(200), nullable=False),
        sa.Column('language', sa.String(64), nullable=False), sa.Column('name', sa.String(200), nullable=False),
        sa.Column('collector_number', sa.String(64), nullable=False), sa.UniqueConstraint('provider', 'external_id', 'language'))
    op.create_index('ix_tcg_cards_expansion_id', 'tcg_cards', ['expansion_id'])
    op.add_column('customer_submission_entries', sa.Column('catalog_card_id', sa.Uuid(), sa.ForeignKey('tcg_cards.id'), nullable=True))


def downgrade():
    op.drop_column('customer_submission_entries', 'catalog_card_id')
    op.drop_table('tcg_cards')
    op.drop_table('tcg_expansions')
    op.drop_table('tcg_games')
