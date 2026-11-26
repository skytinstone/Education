"""하네스: AI 실행 기록 (agent_runs)

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-11-26 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('problem_id', sa.String(length=64), sa.ForeignKey('problems.id', ondelete='SET NULL'), nullable=True),
        sa.Column('harness_version', sa.String(length=16), nullable=False),
        sa.Column('prompt_versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('input', sa.Text(), server_default='', nullable=False),
        sa.Column('output', sa.Text(), server_default='', nullable=False),
        sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('cost_usd', sa.Numeric(12, 6), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_agent_runs_kind', 'agent_runs', ['kind'])
    op.create_index('ix_agent_runs_user_id', 'agent_runs', ['user_id'])
    op.create_index('ix_agent_runs_problem_id', 'agent_runs', ['problem_id'])
    op.create_index('ix_agent_runs_harness_version', 'agent_runs', ['harness_version'])


def downgrade() -> None:
    op.drop_table('agent_runs')
