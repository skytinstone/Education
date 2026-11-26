"""AI 학습 플래너 (study_plans) · 문제 Deep Dive (deep_dives)

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-11-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'study_plans',
        sa.Column('project_id', sa.UUID(), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('review', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('feedback', sa.Text(), server_default='', nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('done', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_study_plans_user_id', 'study_plans', ['user_id'])
    op.create_table(
        'deep_dives',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problem_id', sa.String(length=64), sa.ForeignKey('problems.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('feedback', sa.String(length=12), nullable=True),
        sa.Column('rounds', sa.SmallInteger(), server_default='1', nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('user_id', 'problem_id', name='uq_deep_dive_user_problem'),
        sa.CheckConstraint("feedback IN ('understood', 'confused')", name='deep_dive_feedback'),
    )


def downgrade() -> None:
    op.drop_table('deep_dives')
    op.drop_index('ix_study_plans_user_id', table_name='study_plans')
    op.drop_table('study_plans')
