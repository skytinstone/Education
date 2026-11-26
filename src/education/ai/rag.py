"""RAG — 문제 임베딩 저장과 의미 검색 (pgvector · LangChain OpenAIEmbeddings).

쓰는 곳
- 문제 생성 본보기 (services/generator.py): 요청과 비슷한 '좋은 문제'(성적표 C·D 등급 제외)를 골라 결을 따르게 한다
- 중복 확인 (services/generator.py): 같은 개념에 의미가 거의 같은 문제가 있으면 새 문제를 버린다
- 대화 에이전트의 search_problems 도구 (ai/tutor_agent.py)

누가 볼 수 있는지는 항상 problems 와 조인해서 거른다 — 공용 문제(owner 없음) 또는 그 사용자가 올린 기출만.
임베딩을 못 만들면(키 없음·오류) 조용히 빈 결과를 돌려주고, 부르는 쪽은 기존 방식(개념 ID 로 고르기)으로 간다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.ai import models
from education.config import get_settings
from education.db import models as m
from education.schemas import VerificationStatus

log = logging.getLogger(__name__)
BATCH = 96


def problem_text(p: m.Problem) -> str:
    parts = [p.stem]
    if p.choices:
        parts.append(" / ".join(p.choices))
    return "\n".join(parts)[:4000]


def embed(db: Session, texts: list[str], *, user: m.User | None = None, embedder: models.Embedder | None = None) -> list[list[float]] | None:
    """여러 글을 임베딩한다 (비용은 llm_calls 에 'embed' 로 남김). 못 하면 None."""
    if not texts:
        return []
    emb = embedder or models.get_embedder()
    if emb is None:
        return None
    s = get_settings()
    started = time.monotonic()
    try:
        vecs = [v for i in range(0, len(texts), BATCH) for v in emb.embed_documents(texts[i:i + BATCH])]
    except Exception as e:  # API 오류
        log.warning("임베딩 실패: %s", e)
        db.add(m.LLMCall(purpose="embed", model=s.embedding_model, ok=False, error=str(e)[:500], user_id=user.id if user else None))
        db.flush()
        return None
    n = models.token_count(texts)
    price = models.Usage(model=s.embedding_model, input_tokens=n).cost_usd
    db.add(m.LLMCall(purpose="embed", model=s.embedding_model, ok=True, user_id=user.id if user else None, cost_usd=price,
                     input_tokens=n, output_tokens=0, latency_ms=int((time.monotonic() - started) * 1000)))
    db.flush()
    return vecs


def index(db: Session, problems: list[m.Problem], *, vectors: list[list[float]] | None = None,
          embedder: models.Embedder | None = None) -> int:
    """문제 임베딩을 저장한다 (이미 있으면 건너뜀). vectors 를 주면 그대로 쓴다."""
    have = set(db.scalars(select(m.ProblemEmbedding.problem_id).where(
        m.ProblemEmbedding.problem_id.in_([p.id for p in problems])))) if problems else set()
    todo = [p for p in problems if p.id not in have]
    if not todo:
        return 0
    if vectors is None:
        vectors = embed(db, [problem_text(p) for p in todo], embedder=embedder)
        if vectors is None:
            return 0
    else:
        vectors = [v for p, v in zip(problems, vectors) if p.id not in have]
    model = get_settings().embedding_model
    db.execute(insert(m.ProblemEmbedding).values([{"problem_id": p.id, "embedding": v, "model": model}
                                                  for p, v in zip(todo, vectors)]).on_conflict_do_nothing())
    db.flush()
    return len(todo)


def backfill(db: Session, limit: int = 2000, *, embedder: models.Embedder | None = None) -> int:
    """임베딩이 없는 검증된 문제를 채운다 (매일 아침 알림 작업 · python -m education.ai.index)."""
    q = (select(m.Problem).outerjoin(m.ProblemEmbedding, m.ProblemEmbedding.problem_id == m.Problem.id)
         .where(m.ProblemEmbedding.problem_id.is_(None), m.Problem.verification != VerificationStatus.REJECTED)
         .order_by(m.Problem.created_at.desc()).limit(limit))
    problems = list(db.scalars(q))
    done = 0
    for i in range(0, len(problems), BATCH):
        done += index(db, problems[i:i + BATCH], embedder=embedder)
    return done


@dataclass
class Hit:
    problem: m.Problem
    similarity: float  # 1 - 코사인 거리 (1 이면 같음)


def similar(db: Session, vector: list[float], *, user: m.User | None, concept_id: str | None = None, k: int = 5,
            exclude: list[str] | None = None, good_only: bool = False, verified_only: bool = True,
            only: list[str] | None = None) -> list[Hit]:
    """벡터와 가장 가까운 문제 — 이 사용자가 볼 수 있는 것만."""
    dist = m.ProblemEmbedding.embedding.cosine_distance(vector)
    q = (select(m.Problem, dist.label("d")).join(m.ProblemEmbedding, m.ProblemEmbedding.problem_id == m.Problem.id)
         .where(or_(m.Problem.owner_user_id.is_(None), m.Problem.owner_user_id == (user.id if user else None))))
    if verified_only:
        q = q.where(m.Problem.verification == VerificationStatus.VERIFIED)
    if concept_id:
        q = q.join(m.ProblemConcept, m.ProblemConcept.problem_id == m.Problem.id).where(m.ProblemConcept.concept_id == concept_id)
    if exclude:
        q = q.where(m.Problem.id.not_in(exclude))
    if only is not None:
        q = q.where(m.Problem.id.in_(only))
    if good_only:  # 문제 성적표에서 C·D 를 받은 문제는 본보기로 쓰지 않는다 (아직 성적이 없으면 괜찮음)
        q = q.outerjoin(m.ProblemStats, m.ProblemStats.problem_id == m.Problem.id).where(
            or_(m.ProblemStats.grade.is_(None), m.ProblemStats.grade.in_(("A", "B"))))
    return [Hit(p, 1 - float(d)) for p, d in db.execute(q.order_by(dist).limit(k))]


def search(db: Session, user: m.User | None, query: str, *, concept_id: str | None = None, k: int = 5,
           good_only: bool = False, embedder: models.Embedder | None = None) -> list[Hit]:
    vec = embed(db, [query], user=user, embedder=embedder)
    return similar(db, vec[0], user=user, concept_id=concept_id, k=k, good_only=good_only) if vec else []


def duplicates(db: Session, vectors: list[list[float]], *, concept_id: str, user: m.User | None,
               threshold: float | None = None) -> list[Hit | None]:
    """새 문제마다 같은 개념에서 가장 비슷한 기존 문제 — 기준을 넘으면 그 문제, 아니면 None."""
    t = get_settings().rag_duplicate_similarity if threshold is None else threshold
    out: list[Hit | None] = []
    for v in vectors:
        hit = similar(db, v, user=user, concept_id=concept_id, k=1)
        out.append(hit[0] if hit and hit[0].similarity >= t else None)
    return out


def coverage(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(m.Problem).where(m.Problem.verification != VerificationStatus.REJECTED))
    done = db.scalar(select(func.count()).select_from(m.ProblemEmbedding))
    return {"problems": total or 0, "embedded": done or 0}
