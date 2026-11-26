"""하네스 4단계: 가드레일 기록 (guard_events) · 사람 검토 큐 (review_items)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-11-27 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'guard_events',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('flags', postgresql.ARRAY(sa.String(length=60)), nullable=False),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('detail', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_guard_events_user_id', 'guard_events', ['user_id'])
    op.create_index('ix_guard_events_created', 'guard_events', ['created_at'])
    op.create_table(
        'review_items',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('problem_id', sa.String(length=64), sa.ForeignKey('problems.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=8), server_default='open', nullable=False),
        sa.Column('answer_before', sa.Text(), nullable=True),
        sa.Column('answer_after', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), server_default='', nullable=False),
        sa.Column('decided_by', sa.UUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('open', 'keep', 'fix', 'hide')", name='review_item_status'),
    )
    op.create_index('ix_review_items_problem_id', 'review_items', ['problem_id'])
    op.create_index('uq_review_items_open', 'review_items', ['problem_id'], unique=True, postgresql_where=sa.text("status = 'open'"))


def downgrade() -> None:
    op.drop_table('review_items')
    op.drop_table('guard_events')
