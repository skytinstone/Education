"""문제 성적표 (problem_stats)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-11-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'problem_stats',
        sa.Column('problem_id', sa.String(length=64), sa.ForeignKey('problems.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('n', sa.Integer(), nullable=False),
        sa.Column('p', sa.Float(), nullable=False),
        sa.Column('b', sa.Float(), nullable=False),
        sa.Column('disc', sa.Float(), nullable=True),
        sa.Column('observed_difficulty', sa.SmallInteger(), nullable=False),
        sa.Column('choices', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('flags', postgresql.ARRAY(sa.String(length=20)), server_default='{}', nullable=False),
        sa.Column('grade', sa.String(length=1), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('problem_stats')
