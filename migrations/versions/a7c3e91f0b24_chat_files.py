"""대화 첨부 파일 (chat_files)

Revision ID: a7c3e91f0b24
Revises: fd4461018b0d
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c3e91f0b24'
down_revision: Union[str, Sequence[str], None] = 'fd4461018b0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_files',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chat_files_message_id'), 'chat_files', ['message_id'], unique=False)
    op.create_index(op.f('ix_chat_files_user_id'), 'chat_files', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_files_user_id'), table_name='chat_files')
    op.drop_index(op.f('ix_chat_files_message_id'), table_name='chat_files')
    op.drop_table('chat_files')
