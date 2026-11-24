"""Notion 연결 (notion_links) — 암호화한 토큰 · 저장 공간 · 이미 저장한 결과

Revision ID: f6c1d8e2a9b3
Revises: e5b8c2d4f7a1
Create Date: 2026-11-24 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6c1d8e2a9b3'
down_revision: Union[str, Sequence[str], None] = 'e5b8c2d4f7a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notion_links',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_sealed', sa.Text(), nullable=False),
        sa.Column('workspace_name', sa.String(length=200), nullable=True),
        sa.Column('workspace_id', sa.String(length=64), nullable=True),
        sa.Column('root_page_id', sa.String(length=64), nullable=True),
        sa.Column('exam_db_id', sa.String(length=64), nullable=True),
        sa.Column('interview_db_id', sa.String(length=64), nullable=True),
        sa.Column('auto', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('notion_links')
