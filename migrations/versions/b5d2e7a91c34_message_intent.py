"""대화 답변의 의도·이어서 보낼 제안 (messages.intent, messages.suggestions), 답변 중단 (chat_stops)

Revision ID: b5d2e7a91c34
Revises: a7c3e91f0b24
Create Date: 2026-11-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b5d2e7a91c34'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91f0b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('intent', sa.String(length=24), nullable=True))
    op.add_column('messages', sa.Column('suggestions', postgresql.ARRAY(sa.String(length=80)), server_default='{}', nullable=False))
    op.create_table(
        'chat_stops',
        sa.Column('ref', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('ref'),
    )


def downgrade() -> None:
    op.drop_table('chat_stops')
    op.drop_column('messages', 'suggestions')
    op.drop_column('messages', 'intent')
