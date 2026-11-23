"""대화 답변이 화면에 시키는 일 (messages.action) — 예: 오른쪽 패널에 시험 화면 열기

Revision ID: d3a9b6c1e5f2
Revises: c8e1f4a2d907
Create Date: 2026-11-23 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd3a9b6c1e5f2'
down_revision: Union[str, Sequence[str], None] = 'c8e1f4a2d907'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('action', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'action')
