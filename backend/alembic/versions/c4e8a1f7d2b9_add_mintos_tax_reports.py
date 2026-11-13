"""add mintos_tax_reports table

Mintos's annual tax report, one row per year. See DEVLOG "Step 3u.113".

Revision ID: c4e8a1f7d2b9
Revises: b7d2e9f4a1c3
Create Date: 2026-11-13 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a1f7d2b9'
down_revision: Union[str, Sequence[str], None] = 'b7d2e9f4a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mintos_tax_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('figures', sa.JSON(), nullable=False),
    sa.Column('imported_at', sa.DateTime(), nullable=False),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mintos_tax_reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mintos_tax_reports_year'), ['year'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('mintos_tax_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mintos_tax_reports_year'))
    op.drop_table('mintos_tax_reports')
