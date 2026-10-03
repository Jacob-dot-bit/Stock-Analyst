"""drop instrument_commentaries table

The optional paid qualitative commentary feature was removed; its cache
table goes with it. Downgrade recreates the empty table.

Revision ID: 5b1e7c2d9a40
Revises: 0873d0d3f871
Create Date: 2026-10-03 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b1e7c2d9a40'
down_revision: Union[str, Sequence[str], None] = '0873d0d3f871'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('instrument_commentaries')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('instrument_commentaries',
    sa.Column('instrument_id', sa.Integer(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.Column('model', sa.String(length=40), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('instrument_id')
    )
