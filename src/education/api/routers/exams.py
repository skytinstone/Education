"""시험 기록 — 화면에서 본 시험의 점수·걸린 시간·문항별 결과를 남겨, 점수 추이와 오래 걸린 문항을 보여 준다.

채점 자체는 문항마다 /api/attempts 로 이미 했고 (오답노트도 거기서 생김), 여기는 한 번의 시험을 묶어 기록만 한다.
"""

from uuid import UUID

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from education.api.deps import DB, CurrentUser, owned
from education.db import models as m

router = APIRouter(tags=["시험 기록"])


class ExamItemIn(BaseModel):
    problem_id: str = Field(max_length=64)
    number: int | None = Field(default=None, ge=0, le=9999)
    my: str = Field(default="", max_length=200)          # 내 답 (안 풀면 빈 값)
    answer: str | None = Field(default=None, max_length=200)
    correct: bool | None = None                           # None = 정답이 없어 채점 못 함
    points: int = Field(default=0, ge=0, le=100)
    sec: int = Field(default=0, ge=0, le=86_400)          # 이 문항을 본 시간


class ExamIn(BaseModel):
    title: str = Field(max_length=200)
    scope: str | None = Field(default=None, max_length=80)
    per: int = Field(default=1, ge=1, le=4)
    time_limit_sec: int | None = Field(default=None, ge=0, le=86_400)
    used_sec: int = Field(ge=0, le=86_400)
    auto_submitted: bool = False
    items: list[ExamItemIn] = Field(min_length=1, max_length=300)


def _summary(r: m.ExamRecord) -> dict:
    return {"id": str(r.id), "project_id": str(r.project_id) if r.project_id else None, "title": r.title, "scope": r.scope,
            "per": r.per, "time_limit_sec": r.time_limit_sec, "used_sec": r.used_sec, "auto_submitted": r.auto_submitted,
            "score": r.score, "total_points": r.total_points, "correct": r.correct, "total": r.total,
            "skipped": r.skipped, "ungraded": r.ungraded,
            "rate": round(r.score / r.total_points, 4) if r.total_points else None, "created_at": r.created_at.isoformat()}


@router.post("/projects/{project_id}/exams", status_code=status.HTTP_201_CREATED)
def save_exam(project_id: UUID, body: ExamIn, user: CurrentUser, db: DB) -> dict:
    project = owned(db, m.Project, project_id, user)
    items = [i.model_dump() for i in body.items]
    rec = m.ExamRecord(
        user_id=user.id, project_id=project.id, title=body.title.strip() or project.name, scope=body.scope, per=body.per,
        time_limit_sec=body.time_limit_sec or None, used_sec=body.used_sec, auto_submitted=body.auto_submitted,
        score=sum(i["points"] for i in items if i["correct"]), total_points=sum(i["points"] for i in items),
        correct=sum(1 for i in items if i["correct"]), total=len(items),
        skipped=sum(1 for i in items if not i["my"].strip()), ungraded=sum(1 for i in items if i["correct"] is None and i["my"].strip()),
        items=items,
    )
    db.add(rec)
    db.commit()
    prev = db.scalars(select(m.ExamRecord).where(m.ExamRecord.user_id == user.id, m.ExamRecord.project_id == project.id,
                                                 m.ExamRecord.id != rec.id)
                      .order_by(m.ExamRecord.created_at.desc()).limit(50)).all()
    rates = [p.score / p.total_points for p in prev if p.total_points]
    return {**_summary(rec), "previous_rate": rates[0] if rates else None, "best_rate": max(rates) if rates else None,
            "attempts": len(prev) + 1}


@router.get("/projects/{project_id}/exams")
def list_exams(project_id: UUID, user: CurrentUser, db: DB) -> list[dict]:
    owned(db, m.Project, project_id, user)
    rows = db.scalars(select(m.ExamRecord).where(m.ExamRecord.user_id == user.id, m.ExamRecord.project_id == project_id)
                      .order_by(m.ExamRecord.created_at.desc()).limit(100))
    return [_summary(r) for r in rows]


@router.get("/exams/{exam_id}")
def exam_detail(exam_id: UUID, user: CurrentUser, db: DB) -> dict:
    r = owned(db, m.ExamRecord, exam_id, user)
    stems = {p.id: (p.stem, p.choices) for p in db.scalars(select(m.Problem).where(m.Problem.id.in_([i["problem_id"] for i in r.items])))}
    items = [{**i, "stem": stems.get(i["problem_id"], ("", None))[0], "choices": stems.get(i["problem_id"], ("", None))[1]} for i in r.items]
    return {**_summary(r), "items": items}


@router.delete("/exams/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exam(exam_id: UUID, user: CurrentUser, db: DB) -> Response:
    r = owned(db, m.ExamRecord, exam_id, user)
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

