"""결제·구독에 테스트 여부 (is_test) — 운영 콘솔 매출에서 PortOne 테스트 결제를 뺀다

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('billing_payments', sa.Column('is_test', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('subscriptions', sa.Column('is_test', sa.Boolean(), server_default='false', nullable=False))
    # 이 컬럼이 생기기 전의 결제는 모두 테스트 채널에서만 있었다 (실연동 전)
    op.execute("UPDATE billing_payments SET is_test = true")
    op.execute("UPDATE subscriptions SET is_test = true")


def downgrade() -> None:
    op.drop_column('subscriptions', 'is_test')
    op.drop_column('billing_payments', 'is_test')
