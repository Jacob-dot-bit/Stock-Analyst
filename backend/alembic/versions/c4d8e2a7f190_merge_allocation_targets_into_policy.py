"""merge allocation_targets into personal_policy_limits

An asset-class target range is a policy limit with dimension="category" —
two tables held the same kind of rule. Copies every target over and drops
the old table. Where a category limit already exists, its bounds win and
only a missing bound is filled from the target, so nothing set by hand is
overwritten. See DEVLOG "Step 3u.101".

Revision ID: c4d8e2a7f190
Revises: 8f3a6c1d2e54
Create Date: 2026-11-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d8e2a7f190'
down_revision: Union[str, Sequence[str], None] = '8f3a6c1d2e54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    targets = bind.execute(sa.text("SELECT category, min_pct, max_pct FROM allocation_targets")).fetchall()
    for category, min_pct, max_pct in targets:
        existing = bind.execute(
            sa.text(
                "SELECT id, min_pct, max_pct FROM personal_policy_limits "
                "WHERE dimension = 'category' AND target = :target"
            ),
            {"target": category},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO personal_policy_limits (dimension, target, min_pct, max_pct) "
                    "VALUES ('category', :target, :min_pct, :max_pct)"
                ),
                {"target": category, "min_pct": min_pct, "max_pct": max_pct},
            )
        else:
            limit_id, current_min, current_max = existing
            bind.execute(
                sa.text("UPDATE personal_policy_limits SET min_pct = :min_pct, max_pct = :max_pct WHERE id = :id"),
                {
                    "id": limit_id,
                    "min_pct": current_min if current_min is not None else min_pct,
                    "max_pct": current_max if current_max is not None else max_pct,
                },
            )

    with op.batch_alter_table('allocation_targets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_allocation_targets_category'))
    op.drop_table('allocation_targets')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('allocation_targets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('min_pct', sa.Float(), nullable=False),
    sa.Column('max_pct', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('allocation_targets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_allocation_targets_category'), ['category'], unique=True)

    # Category limits stay in the policy too: they can't be told apart from
    # ones created there directly, and keeping them loses nothing.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO allocation_targets (category, min_pct, max_pct) "
            "SELECT substr(target, 1, 20), COALESCE(min_pct, 0), COALESCE(max_pct, 100) "
            "FROM personal_policy_limits WHERE dimension = 'category' AND target IS NOT NULL"
        )
    )
