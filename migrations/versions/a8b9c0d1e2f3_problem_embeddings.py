"""RAG: pgvector 확장과 문제 임베딩 (problem_embeddings)

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-11-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DB 이미지가 pgvector/pgvector 여야 한다 (docker-compose*.yml · CI)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        'problem_embeddings',
        sa.Column('problem_id', sa.String(length=64), sa.ForeignKey('problems.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('embedding', Vector(1536), nullable=False),
        sa.Column('model', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    # 코사인 거리 근사 최근접 검색
    op.execute("CREATE INDEX ix_problem_embeddings_hnsw ON problem_embeddings USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.drop_table('problem_embeddings')
