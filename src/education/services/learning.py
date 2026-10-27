"""채점, 오답노트, 약점 통계."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.api.dto import AttemptIn, AttemptResult, AttemptView, ProblemView, WeakConcept
from education.config import get_settings
from education.db import models as m


def visible_to(user: m.User):
    """공용 문제이거나 내가 올린·만든 문제 (남이 올린 기출은 보이지 않음)."""
    return (m.Problem.owner_user_id.is_(None)) | (m.Problem.owner_user_id == user.id)


def is_correct(problem: m.Problem, answer: str) -> bool:
    """단답형은 '007', '1,000', ' 12 ' 같은 표기 차이를 무시하고 수로 비교한다."""
    given = answer.strip()
    if problem.problem_type == "short_answer":
        try:
            return int(given.replace(",", "")) == int(problem.answer)
        except ValueError:
            return given == problem.answer
    return given == problem.answer


def problem_views(db: Session, user: m.User, problem_ids: list[str], session_id: UUID | None = None) -> list[ProblemView]:
    """문제 id 순서대로 보여 줄 문제. session_id 가 있으면 그 대화에서 마지막으로 푼 기록과 정답·해설을 붙인다."""
    if not problem_ids:
        return []
    problems = {p.id: p for p in db.scalars(select(m.Problem).where(m.Problem.id.in_(problem_ids), visible_to(user)))}
    saved = set(db.scalars(select(m.SavedProblem.problem_id).where(
        m.SavedProblem.user_id == user.id, m.SavedProblem.problem_id.in_(problem_ids))))
    last: dict[str, m.Attempt] = {}
    if session_id:
        rows = db.scalars(
            select(m.Attempt).where(m.Attempt.user_id == user.id, m.Attempt.session_id == session_id,
                                    m.Attempt.problem_id.in_(problem_ids)).order_by(m.Attempt.created_at))
        last = {a.problem_id: a for a in rows}

    views = []
    for pid in problem_ids:
        p = problems.get(pid)
        if p is None:
            continue
        a = last.get(pid)
        views.append(ProblemView(
            id=p.id, domain=p.domain, concept_ids=p.concept_ids, difficulty=p.difficulty, problem_type=p.problem_type,
            stem=p.stem, choices=p.choices, saved=pid in saved,
            attempt=AttemptView(answer=a.answer, correct=a.correct) if a else None,
            answer=p.answer if a else None, solution=p.solution if a else None,
        ))
    return views


def submit_answer(db: Session, user: m.User, body: AttemptIn) -> AttemptResult:
    """풀이를 기록한다. 틀리면 오답노트에 넣고, 오답노트에 있던 문제를 맞히면 극복 처리한다."""
    problem = db.get(m.Problem, body.problem_id)
    if problem is None or problem.owner_user_id not in (None, user.id) or not problem.answer:
        raise HTTPException(404, "문제를 찾을 수 없어요")
    for model, obj_id in ((m.Project, body.project_id), (m.ChatSession, body.session_id)):
        if obj_id is not None:
            obj = db.get(model, obj_id)
            if obj is None or obj.user_id != user.id:
                raise HTTPException(404, "찾을 수 없어요")

    correct = is_correct(problem, body.answer)
    db.add(m.Attempt(user_id=user.id, problem_id=problem.id, project_id=body.project_id,
                     session_id=body.session_id, answer=body.answer, correct=correct))

    note_id, resolved = None, False
    open_note = (m.WrongNote.user_id == user.id) & (m.WrongNote.problem_id == problem.id) & (m.WrongNote.resolved_at.is_(None))
    if correct:
        resolved = db.scalar(update(m.WrongNote).where(open_note)
                             .values(resolved_at=func.now()).returning(m.WrongNote.id)) is not None
    else:
        # 동시에 두 번 틀려도 '안 푼 오답'은 하나만 (부분 유니크 인덱스)
        db.execute(insert(m.WrongNote)
                   .values(user_id=user.id, problem_id=problem.id, project_id=body.project_id, answer=body.answer)
                   .on_conflict_do_nothing(index_elements=["user_id", "problem_id"], index_where=m.WrongNote.resolved_at.is_(None)))
        note_id = db.scalar(select(m.WrongNote.id).where(open_note))
    if body.session_id:
        db.execute(update(m.ChatSession).where(m.ChatSession.id == body.session_id).values(updated_at=func.now()))
    db.commit()
    return AttemptResult(correct=correct, answer=problem.answer, solution=problem.solution,
                         wrong_note_id=note_id, resolved=resolved)


def concept_stats(db: Session, user: m.User, *, project_id: UUID | None = None, domain: str | None = None,
                  min_attempts: int = 1) -> list[WeakConcept]:
    """개념별 정답률 — 낮은 순 (약점 분석)."""
    q = (select(m.Concept.id, m.Concept.name, func.count().label("n"), func.sum(cast(m.Attempt.correct, Integer)).label("ok"))
         .select_from(m.Attempt)
         .join(m.ProblemConcept, m.ProblemConcept.problem_id == m.Attempt.problem_id)
         .join(m.Concept, m.Concept.id == m.ProblemConcept.concept_id)
         .where(m.Attempt.user_id == user.id)
         .group_by(m.Concept.id, m.Concept.name)
         .having(func.count() >= min_attempts))
    if project_id:
        q = q.where(m.Attempt.project_id == project_id)
    if domain:
        q = q.where(m.Concept.domain == domain)
    rows = [WeakConcept(concept_id=cid, name=name, attempts=n, correct=ok, accuracy=ok / n) for cid, name, n, ok in db.execute(q)]
    return sorted(rows, key=lambda w: (w.accuracy, -w.attempts))


def accuracy(db: Session, user: m.User, *, project_id: UUID | None = None, domain: str | None = None) -> float | None:
    q = select(func.avg(cast(m.Attempt.correct, Integer))).where(m.Attempt.user_id == user.id)
    if project_id:
        q = q.where(m.Attempt.project_id == project_id)
    if domain:
        q = q.join(m.Problem, m.Problem.id == m.Attempt.problem_id).where(m.Problem.domain == domain)
    v = db.scalar(q)
    return float(v) if v is not None else None


def _local_day():
    """풀이 시각을 설정한 시간대(기본 Asia/Seoul)의 날짜로."""
    return func.date(func.timezone(get_settings().timezone, m.Attempt.created_at))


def local_today(db: Session) -> date:
    return db.scalar(select(func.date(func.timezone(get_settings().timezone, func.now()))))


def today_count(db: Session, user: m.User) -> int:
    return db.scalar(select(func.count()).where(m.Attempt.user_id == user.id, _local_day() == local_today(db)))


def streak(db: Session, user: m.User) -> int:
    """오늘부터 거꾸로 하루도 빠짐없이 문제를 푼 날 수."""
    days = set(db.scalars(select(_local_day()).distinct().where(
        m.Attempt.user_id == user.id, m.Attempt.created_at >= datetime.now(timezone.utc) - timedelta(days=400))))
    n, d = 0, local_today(db)
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n
