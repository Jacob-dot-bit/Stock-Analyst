"""add bank_operations table

Every line of the bank account export, for the budget view. See DEVLOG
"Step 3u.92".

Revision ID: 8f3a6c1d2e54
Revises: 5b1e7c2d9a40
Create Date: 2026-11-13 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f3a6c1d2e54'
down_revision: Union[str, Sequence[str], None] = '5b1e7c2d9a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('bank_operations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('executed_on', sa.Date(), nullable=False),
    sa.Column('value_date', sa.Date(), nullable=True),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('broker', sa.String(length=20), nullable=True),
    sa.Column('own_transfer', sa.Boolean(), nullable=False),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bank_operations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bank_operations_account'), ['account'], unique=False)
        batch_op.create_index(batch_op.f('ix_bank_operations_executed_on'), ['executed_on'], unique=False)
        batch_op.create_index(batch_op.f('ix_bank_operations_external_id'), ['external_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('bank_operations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bank_operations_external_id'))
        batch_op.drop_index(batch_op.f('ix_bank_operations_executed_on'))
        batch_op.drop_index(batch_op.f('ix_bank_operations_account'))
    op.drop_table('bank_operations')
