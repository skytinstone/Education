"""답글: 질문이 인용한 앞 답변의 부분 (messages.quote)

Revision ID: c8e1f4a2d907
Revises: b5d2e7a91c34
Create Date: 2026-11-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8e1f4a2d907'
down_revision: Union[str, Sequence[str], None] = 'b5d2e7a91c34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('quote', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'quote')
