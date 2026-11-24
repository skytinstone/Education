"""AI 면접 모드 — 종류 목록, 시작, 답변, 마치기(리포트), 기록 (services/interview.py).

녹음 파일은 받지 않는다. 브라우저가 받아쓴 글과 걸린 시간만 온다.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from education.api.deps import DB, CurrentUser, owned
from education.db import models as m
from education.services import interview as iv_svc

router = APIRouter(prefix="/interviews", tags=["AI 면접"])


class InterviewIn(BaseModel):
    kind: str = Field(max_length=20)
    setup: dict[str, str] = Field(default_factory=dict, max_length=20)


class AdjustIn(BaseModel):
    choice: str = Field(pattern="^(easier|same|harder)$")  # 쉬운 질문 · 비슷한 질문 · 어려운 질문


class AnswerIn(BaseModel):
    text: str = Field(default="", max_length=6000)  # 빈 값 = 넘어가기
    sec: int = Field(default=0, ge=0, le=1800)


def _kind_out(k: iv_svc.Kind) -> dict:
    return {"key": k.key, "name": k.name, "desc": k.desc, "lang": k.lang, "mains": k.mains, "follow_ups": k.follow_ups,
            "prep_sec": k.prep_sec, "answer_sec": k.answer_sec, "levels": list(k.levels), "level_note": k.level_note,
            "time_note": k.time_note, "fixed": k.fixed, "survey_min": k.survey_min, "survey_keys": list(k.survey_keys),
            "adjust_after": k.adjust_after, "replays": k.replays, "level_bands": dict(k.level_bands),
            "steps": [{"title": t, "sub": sub, "keys": list(keys)} for t, sub, keys in k.steps],
            "fields": [{"key": f.key, "label": f.label, "placeholder": f.placeholder, "kind": f.kind,
                        "options": list(f.options), "required": f.required, "max_len": f.max_len, "min_pick": f.min_pick} for f in k.fields]}


def _summary(iv: m.Interview) -> dict:
    k = iv_svc.KINDS.get(iv.kind)
    rep = iv.report or {}
    return {"id": str(iv.id), "kind": iv.kind, "kind_name": k.name if k else iv.kind, "status": iv.status,
            "level": rep.get("level") or None, "score": rep.get("score"),
            "questions": len(iv.turns), "created_at": iv.created_at.isoformat(),
            "finished_at": iv.finished_at.isoformat() if iv.finished_at else None}


def _detail(iv: m.Interview) -> dict:
    k = iv_svc.KINDS[iv.kind]
    i = iv_svc.current(iv)
    mains_done = sum(1 for t in iv.turns if not t.get("follow") and t.get("ans") is not None)
    return {**_summary(iv), "kind_info": _kind_out(k), "lang": iv.lang, "setup": iv.setup, "by_ai": iv.by_ai,
            "turns": iv.turns, "current": i, "mains": len(iv.plan), "mains_done": mains_done, "report": iv.report}


@router.get("/kinds")
def kinds(user: CurrentUser) -> list[dict]:
    return [_kind_out(k) for k in iv_svc.KINDS.values()]


@router.post("", status_code=status.HTTP_201_CREATED)
def start(body: InterviewIn, user: CurrentUser, db: DB) -> dict:
    kind = iv_svc.KINDS.get(body.kind)
    if kind is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "없는 면접 종류예요")
    setup = iv_svc.clean_setup(kind, body.setup)
    if miss := iv_svc.missing_fields(kind, setup):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{', '.join(miss)}을(를) 골라 주세요")
    iv = iv_svc.start(db, user, kind, setup)
    db.commit()
    return _detail(iv)


@router.get("")
def list_interviews(user: CurrentUser, db: DB) -> list[dict]:
    rows = db.scalars(select(m.Interview).where(m.Interview.user_id == user.id)
                      .order_by(m.Interview.created_at.desc()).limit(50))
    return [_summary(r) for r in rows]


@router.get("/{interview_id}")
def detail(interview_id: UUID, user: CurrentUser, db: DB) -> dict:
    return _detail(owned(db, m.Interview, interview_id, user))


@router.post("/{interview_id}/answers")
def answer(interview_id: UUID, body: AnswerIn, user: CurrentUser, db: DB) -> dict:
    iv = owned(db, m.Interview, interview_id, user)
    if iv.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 끝난 면접이에요")
    iv_svc.answer(db, user, iv, body.text, body.sec)
    db.commit()
    return _detail(iv)


@router.post("/{interview_id}/adjust")
def adjust(interview_id: UUID, body: AdjustIn, user: CurrentUser, db: DB) -> dict:
    """OPIc 난이도 재조정 — 1차 세션이 끝나면 2차 세션의 난이도를 다시 고른다."""
    iv = owned(db, m.Interview, interview_id, user)
    if iv.status != "adjust":
        raise HTTPException(status.HTTP_409_CONFLICT, "지금은 난이도를 다시 고를 때가 아니에요")
    iv_svc.adjust(db, user, iv, body.choice)
    db.commit()
    return _detail(iv)


@router.post("/{interview_id}/finish")
def finish(interview_id: UUID, user: CurrentUser, db: DB) -> dict:
    """리포트를 만든다. 중간에 마쳐도 답한 질문까지로 만든다."""
    iv = owned(db, m.Interview, interview_id, user)
    iv_svc.finish(db, user, iv)
    db.commit()
    return _detail(iv)


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(interview_id: UUID, user: CurrentUser, db: DB) -> Response:
    db.delete(owned(db, m.Interview, interview_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
