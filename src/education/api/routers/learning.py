"""문제 · 풀이 · 오답노트 · 저장한 문제 · 암기 카드 · 개념 · 통계."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import any_, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import (
    AttemptIn, AttemptResult, CardOut, CardPatch, ConceptDetail, ConceptNoteCreated, ConceptNoteOut, ConceptOut,
    ProblemOut, ProblemView, SolutionReviewIn, StatsOut, WrongNoteOut, WrongNotePatch,
)
from education.db import models as m
from education.schemas import ErrorType
from education.services import learning, lessons, notes, quota, review, solutions, tutor_chat
from education.services.llm import get_llm

router = APIRouter(tags=["학습"])


# ---------- 개념 ----------
@router.get("/concepts", tags=["개념"])
def list_concepts(db: DB) -> list[ConceptOut]:
    q = select(m.Concept).order_by(m.Concept.course_id, m.Concept.level != "subject", m.Concept.position, m.Concept.id)
    return [ConceptOut.model_validate(c) for c in db.scalars(q)]


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
    quota.check(db, user)
    try:
        result = notes.create_note(db, llm, user, concept_id)
    except notes.NoteError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"검증을 통과한 정리를 만들지 못했어요. 잠시 후 다시 시도해 주세요 ({e})") from None
    return ConceptNoteCreated(note=ConceptNoteOut.model_validate(result.note),
                              added_cards=[CardOut.model_validate(c) for c in result.added_cards])


# ---------- AI 사용량 (설정 화면) ----------
@router.get("/usage", tags=["통계"])
def ai_usage(user: CurrentUser, db: DB) -> dict:
    """오늘 · 이번 달 AI 사용량을 한도 대비 비율로 (금액은 보여 주지 않는다)"""
    return quota.summary(db, user)


# ---------- 개념 레슨 · 개념과 대화하기 (라이브러리) ----------
@router.get("/concepts/{concept_id}/lesson", tags=["개념"])
def get_lesson(concept_id: str, user: CurrentUser, db: DB) -> dict | None:
    """모두가 같이 보는 개념 레슨 — 아직 없으면 null."""
    lesson = lessons.get_lesson(db, concept_id)
    return {"concept_id": concept_id, "content": lesson.content, "created_at": lesson.created_at.isoformat()} if lesson else None


@router.post("/concepts/{concept_id}/lesson", tags=["개념"], status_code=status.HTTP_201_CREATED)
def create_lesson(concept_id: str, user: CurrentUser, db: DB) -> dict:
    """레슨을 만들고 검증한다 (1~2분). 이미 있으면 그대로 돌려준다."""
    if db.get(m.Concept, concept_id) is None:
        raise HTTPException(404, "개념을 찾을 수 없어요")
    if lessons.get_lesson(db, concept_id) is None:
        llm = get_llm()
        if llm is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
        quota.check(db, user)
        try:
            lessons.create_lesson(db, llm, user, concept_id)
        except lessons.LessonError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"검증을 통과한 레슨을 만들지 못했어요. 잠시 후 다시 시도해 주세요 ({e})") from None
    return get_lesson(concept_id, user, db)


class ChatIn(BaseModel):
    mode: tutor_chat.Mode = "explain"
    message: str = Field(default="", max_length=4000)
    history: list[tutor_chat.Turn] = Field(default_factory=list, max_length=30)


@router.post("/concepts/{concept_id}/chat", tags=["개념"])
def concept_chat(concept_id: str, body: ChatIn, user: CurrentUser, db: DB) -> dict:
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    quota.check(db, user)
    try:
        return tutor_chat.reply(db, llm, user, concept_id, body.mode, body.history, body.message.strip())
    except tutor_chat.ChatError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None


class ClipIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    visual: dict | None = None


def _clip_out(c: m.ConceptClip) -> dict:
    return {"id": str(c.id), "text": c.text, "visual": c.visual, "created_at": c.created_at.isoformat()}


@router.get("/concepts/{concept_id}/clips", tags=["개념"])
def list_clips(concept_id: str, user: CurrentUser, db: DB) -> list[dict]:
    rows = db.scalars(select(m.ConceptClip).where(m.ConceptClip.user_id == user.id, m.ConceptClip.concept_id == concept_id)
                      .order_by(m.ConceptClip.created_at.desc()).limit(50))
    return [_clip_out(c) for c in rows]


@router.post("/concepts/{concept_id}/clips", tags=["개념"], status_code=status.HTTP_201_CREATED)
def add_clip(concept_id: str, body: ClipIn, user: CurrentUser, db: DB) -> dict:
    if db.get(m.Concept, concept_id) is None:
        raise HTTPException(404, "개념을 찾을 수 없어요")
    visual = body.visual if body.visual and len(str(body.visual)) < 60000 else None
    clip = m.ConceptClip(user_id=user.id, concept_id=concept_id, text=body.text.strip(), visual=visual)
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return _clip_out(clip)


@router.delete("/clips/{clip_id}", tags=["개념"], status_code=status.HTTP_204_NO_CONTENT)
def delete_clip(clip_id: UUID, user: CurrentUser, db: DB) -> Response:
    db.execute(delete(m.ConceptClip).where(m.ConceptClip.id == clip_id, m.ConceptClip.user_id == user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 문제 · 풀이 ----------
@router.get("/problems", tags=["문제"])
def list_problems(db: DB, user: CurrentUser, domain: str | None = None, concept_id: str | None = None) -> list[ProblemOut]:
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


@router.post("/problems/{problem_id}/review", tags=["문제"])
def review_solution(problem_id: str, body: SolutionReviewIn, user: CurrentUser, db: DB) -> review.Review:
    """서술형 풀이를 단계별로 확인해 어디서 틀렸는지 알려 준다 (손글씨 사진도 가능). 아직 답을 내지 않은 문제면 정답은 숨긴다."""
    if not (body.text and body.text.strip()) and not body.image:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "풀이를 적거나 손글씨로 써 주세요")
    p = db.get(m.Problem, problem_id)
    if p is None or p.owner_user_id not in (None, user.id):
        raise HTTPException(404, "문제를 찾을 수 없어요")
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    quota.check(db, user)
    attempted = db.scalar(select(m.Attempt.id).where(m.Attempt.user_id == user.id, m.Attempt.problem_id == problem_id).limit(1)) is not None
    try:
        return review.review_solution(db, llm, user, p, text=body.text, image=body.image, attempted=attempted)
    except review.ImageError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    except review.ReviewError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None


def _solved_problem(db, user, problem_id: str) -> m.Problem:
    """볼 수 있는 문제이고, 이미 답을 낸 문제여야 한다 (풀기 전에 풀이를 미리 보지 않게)."""
    p = db.get(m.Problem, problem_id)
    if p is None or p.owner_user_id not in (None, user.id):
        raise HTTPException(404, "문제를 찾을 수 없어요")
    tried = db.scalar(select(m.Attempt.id).where(m.Attempt.user_id == user.id, m.Attempt.problem_id == problem_id).limit(1))
    if tried is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "먼저 답을 내면 다른 풀이를 볼 수 있어요")
    return p


@router.get("/problems/{problem_id}/methods", tags=["문제"])
def get_methods(problem_id: str, user: CurrentUser, db: DB) -> dict | None:
    """이 문제의 여러 가지 풀이 — 아직 없으면 null."""
    _solved_problem(db, user, problem_id)
    return solutions.get(db, problem_id)


@router.post("/problems/{problem_id}/methods", tags=["문제"], status_code=status.HTTP_201_CREATED)
def create_methods(problem_id: str, user: CurrentUser, db: DB) -> dict:
    """정석 · 그래프 · 빠른 풀이처럼 서로 다른 풀이 2~3가지를 만든다 (20~40초). 이미 있으면 그대로 돌려준다."""
    p = _solved_problem(db, user, problem_id)
    if (cached := solutions.get(db, problem_id)) is not None:
        return cached
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    quota.check(db, user)
    try:
        content = solutions.create(db, llm, user, p)
    except solutions.MethodsError as e:
        db.commit()  # 실패한 호출 기록(비용)은 남긴다
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"다른 풀이를 만들지 못했어요. 잠시 후 다시 시도해 주세요 ({e})") from None
    db.commit()  # 만든 풀이를 저장해야 다음 사람은 AI 를 부르지 않는다
    return content


@router.post("/attempts", tags=["문제"], status_code=status.HTTP_201_CREATED)
def submit_attempt(body: AttemptIn, user: CurrentUser, db: DB) -> AttemptResult:
    """채점. 서술형은 AI 가 채점 기준표로 점수를 매기고 (10~30초), 60% 이상이면 맞힌 것으로 친다."""
    p = db.get(m.Problem, body.problem_id)
    essay = None
    if p is not None and p.problem_type == "essay" and p.owner_user_id in (None, user.id):
        llm = get_llm()
        if llm is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않아 서술형은 채점할 수 없어요")
        quota.check(db, user)
        try:
            essay = review.grade_essay(db, llm, user, p, body.answer)
        except review.ReviewError as e:
            db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return learning.submit_answer(db, user, body, essay=essay)


# ---------- 오답노트 ----------
@router.get("/wrong-notes", tags=["오답노트"])
def list_wrong_notes(user: CurrentUser, db: DB, domain: str | None = None, error_type: ErrorType | None = None,
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
        accuracy_by_domain={d: learning.accuracy(db, user, domain=d) for d in learning.my_domains(db, user)},
        weak_concepts=learning.concept_stats(db, user, min_attempts=3)[:5],
    )
