"""add tax_notices table

The income tax notice of each year, as the tax office printed it. See
DEVLOG "Step 3u.109".

Revision ID: b7d2e9f4a1c3
Revises: 4803a6641224
Create Date: 2026-11-13 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d2e9f4a1c3'
down_revision: Union[str, Sequence[str], None] = '4803a6641224'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('tax_notices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('income_year', sa.Integer(), nullable=False),
    sa.Column('figures', sa.JSON(), nullable=False),
    sa.Column('lines', sa.JSON(), nullable=False),
    sa.Column('imported_at', sa.DateTime(), nullable=False),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tax_notices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tax_notices_income_year'), ['income_year'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tax_notices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tax_notices_income_year'))
    op.drop_table('tax_notices')
