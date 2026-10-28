"""문제 · 풀이 · 오답노트 · 저장한 문제 · 암기 카드 · 개념 · 통계."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import any_, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import (
    AttemptIn, AttemptResult, CardOut, CardPatch, ConceptDetail, ConceptNoteCreated, ConceptNoteOut, ConceptOut,
    ProblemOut, ProblemView, StatsOut, WrongNoteOut, WrongNotePatch,
)
from education.db import models as m
from education.schemas import Domain, ErrorType
from education.services import learning, notes
from education.services.llm import get_llm

router = APIRouter(tags=["학습"])


# ---------- 개념 ----------
@router.get("/concepts", tags=["개념"])
def list_concepts(db: DB) -> list[ConceptOut]:
    return [ConceptOut.model_validate(c) for c in db.scalars(select(m.Concept).order_by(m.Concept.id))]


@router.get("/concepts/{concept_id}", tags=["개념"])
def get_concept(concept_id: str, user: CurrentUser, db: DB) -> ConceptDetail:
    c = db.get(m.Concept, concept_id)
    if c is None:
        raise HTTPException(404, "개념을 찾을 수 없어요")
    path, node = [], c
    while node:
        path.insert(0, ConceptOut.model_validate(node))
        node = db.get(m.Concept, node.parent_id) if node.parent_id else None
    next_concepts = db.scalars(select(m.Concept).where(literal(concept_id) == any_(m.Concept.prerequisites)))
    problem_ids = list(db.scalars(select(m.ProblemConcept.problem_id).where(m.ProblemConcept.concept_id == concept_id)))
    cards = db.scalars(select(m.Card).where(m.Card.user_id == user.id, m.Card.concept_id == concept_id).order_by(m.Card.created_at))
    stats = next((s for s in learning.concept_stats(db, user) if s.concept_id == concept_id), None)
    return ConceptDetail(
        concept=ConceptOut.model_validate(c), path=path, stats=stats,
        next_concepts=[ConceptOut.model_validate(x) for x in next_concepts],
        problems=learning.problem_views(db, user, problem_ids),
        cards=[CardOut.model_validate(k) for k in cards],
    )


@router.get("/concepts/{concept_id}/note", tags=["개념"])
def get_note(concept_id: str, user: CurrentUser, db: DB) -> ConceptNoteOut | None:
    """내 맞춤 개념 정리 — 아직 만들지 않았으면 null."""
    note = db.scalar(select(m.ConceptNote).where(m.ConceptNote.user_id == user.id, m.ConceptNote.concept_id == concept_id))
    return ConceptNoteOut.model_validate(note) if note else None


@router.post("/concepts/{concept_id}/note", tags=["개념"], status_code=status.HTTP_201_CREATED)
def create_note(concept_id: str, user: CurrentUser, db: DB) -> ConceptNoteCreated:
    """내 풀이·오답 기록에 맞춘 개념 정리와 암기 카드를 만들고 검증한다 (1~2분). 이미 있으면 새로 만들어 덮어쓴다."""
    if db.get(m.Concept, concept_id) is None:
        raise HTTPException(404, "개념을 찾을 수 없어요")
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    try:
        result = notes.create_note(db, llm, user, concept_id)
    except notes.NoteError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"검증을 통과한 정리를 만들지 못했어요. 잠시 후 다시 시도해 주세요 ({e})") from None
    return ConceptNoteCreated(note=ConceptNoteOut.model_validate(result.note),
                              added_cards=[CardOut.model_validate(c) for c in result.added_cards])


# ---------- 문제 · 풀이 ----------
@router.get("/problems", tags=["문제"])
def list_problems(db: DB, user: CurrentUser, domain: Domain | None = None, concept_id: str | None = None) -> list[ProblemOut]:
    q = select(m.Problem).where(learning.visible_to(user)).order_by(m.Problem.id)
    if domain:
        q = q.where(m.Problem.domain == domain)
    if concept_id:
        q = q.join(m.ProblemConcept).where(m.ProblemConcept.concept_id == concept_id)
    return [ProblemOut.model_validate(p) for p in db.scalars(q)]


@router.get("/problems/{problem_id}", tags=["문제"])
def get_problem(problem_id: str, db: DB, user: CurrentUser) -> ProblemOut:
    p = db.get(m.Problem, problem_id)
    if p is None or p.owner_user_id not in (None, user.id):
        raise HTTPException(404, "문제를 찾을 수 없어요")
    return ProblemOut.model_validate(p)


@router.post("/attempts", tags=["문제"], status_code=status.HTTP_201_CREATED)
def submit_attempt(body: AttemptIn, user: CurrentUser, db: DB) -> AttemptResult:
    return learning.submit_answer(db, user, body)


# ---------- 오답노트 ----------
@router.get("/wrong-notes", tags=["오답노트"])
def list_wrong_notes(user: CurrentUser, db: DB, domain: Domain | None = None, error_type: ErrorType | None = None,
                     open_only: bool = True, project_id: UUID | None = None) -> list[WrongNoteOut]:
    q = (select(m.WrongNote, m.Problem).join(m.Problem, m.Problem.id == m.WrongNote.problem_id)
         .where(m.WrongNote.user_id == user.id)
         .order_by(m.WrongNote.resolved_at.is_not(None), m.WrongNote.created_at.desc()))
    if domain:
        q = q.where(m.Problem.domain == domain)
    if error_type:
        q = q.where(m.WrongNote.error_type == error_type)
    if open_only:
        q = q.where(m.WrongNote.resolved_at.is_(None))
    if project_id:
        q = q.where(m.WrongNote.project_id == project_id)
    return [WrongNoteOut(id=w.id, problem=ProblemOut.model_validate(p), project_id=w.project_id, answer=w.answer,
                         error_type=w.error_type, created_at=w.created_at, resolved_at=w.resolved_at)
            for w, p in db.execute(q)]


@router.patch("/wrong-notes/{note_id}", tags=["오답노트"])
def update_wrong_note(note_id: UUID, body: WrongNotePatch, user: CurrentUser, db: DB) -> dict:
    owned(db, m.WrongNote, note_id, user).error_type = body.error_type
    db.commit()
    return {"id": note_id, "error_type": body.error_type}


@router.delete("/wrong-notes/{note_id}", tags=["오답노트"], status_code=status.HTTP_204_NO_CONTENT)
def delete_wrong_note(note_id: UUID, user: CurrentUser, db: DB) -> Response:
    db.delete(owned(db, m.WrongNote, note_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 저장한 문제 ----------
@router.get("/saved", tags=["라이브러리"])
def list_saved(user: CurrentUser, db: DB) -> list[ProblemView]:
    ids = list(db.scalars(select(m.SavedProblem.problem_id).where(m.SavedProblem.user_id == user.id)
                          .order_by(m.SavedProblem.created_at)))
    return learning.problem_views(db, user, ids)


@router.put("/saved/{problem_id}", tags=["라이브러리"], status_code=status.HTTP_204_NO_CONTENT)
def save_problem(problem_id: str, user: CurrentUser, db: DB) -> Response:
    p = db.get(m.Problem, problem_id)
    if p is None or p.owner_user_id not in (None, user.id):
        raise HTTPException(404, "문제를 찾을 수 없어요")
    db.execute(insert(m.SavedProblem).values(user_id=user.id, problem_id=problem_id).on_conflict_do_nothing())
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/saved/{problem_id}", tags=["라이브러리"], status_code=status.HTTP_204_NO_CONTENT)
def unsave_problem(problem_id: str, user: CurrentUser, db: DB) -> Response:
    db.execute(delete(m.SavedProblem).where(m.SavedProblem.user_id == user.id, m.SavedProblem.problem_id == problem_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 암기 카드 ----------
@router.get("/cards", tags=["라이브러리"])
def list_cards(user: CurrentUser, db: DB) -> list[CardOut]:
    q = select(m.Card).where(m.Card.user_id == user.id).order_by(m.Card.created_at)
    return [CardOut.model_validate(c) for c in db.scalars(q)]


@router.patch("/cards/{card_id}", tags=["라이브러리"])
def update_card(card_id: UUID, body: CardPatch, user: CurrentUser, db: DB) -> CardOut:
    card = owned(db, m.Card, card_id, user)
    card.known = body.known
    db.commit()
    return CardOut.model_validate(card)


@router.post("/cards/reset", tags=["라이브러리"], status_code=status.HTTP_204_NO_CONTENT)
def reset_cards(user: CurrentUser, db: DB) -> Response:
    db.execute(update(m.Card).where(m.Card.user_id == user.id).values(known=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 통계 ----------
@router.get("/stats", tags=["통계"])
def stats(user: CurrentUser, db: DB) -> StatsOut:
    return StatsOut(
        today_count=learning.today_count(db, user), daily_goal=user.daily_goal, streak=learning.streak(db, user),
        open_notes=db.scalar(select(func.count()).where(m.WrongNote.user_id == user.id, m.WrongNote.resolved_at.is_(None))),
        accuracy_by_domain={d: learning.accuracy(db, user, domain=d) for d in Domain},
        weak_concepts=learning.concept_stats(db, user, min_attempts=3)[:5],
    )
