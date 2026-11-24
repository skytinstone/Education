"""AI 면접 (interviews) — 질문·받아쓴 답·리포트

Revision ID: e5b8c2d4f7a1
Revises: d3a9b6c1e5f2
Create Date: 2026-11-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5b8c2d4f7a1'
down_revision: Union[str, Sequence[str], None] = 'd3a9b6c1e5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'interviews',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('lang', sa.String(length=8), nullable=False),
        sa.Column('setup', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('turns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='active', nullable=False),
        sa.Column('by_ai', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_interviews_user_created', 'interviews', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_interviews_user_created', table_name='interviews')
    op.drop_table('interviews')
