"""AI 학습 플래너 (프로젝트별) · 문제 Deep Dive."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from education.api.deps import DB, CurrentUser, owned
from education.api.routers.learning import _solved_problem
from education.db import models as m
from education.services import deepdive, planner, quota
from education.services.llm import get_llm

router = APIRouter(tags=["학습 플래너"])


def _llm():
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    return llm


# ---------- 학습 플래너 ----------
class PlanReviewIn(BaseModel):
    feedback: str = Field("", max_length=1000)


class PlanTaskIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    done: bool


@router.get("/projects/{project_id}/plan")
def get_plan(project_id: UUID, user: CurrentUser, db: DB) -> dict:
    """남은 기간 · 개념별 분석(내 정답률과 다른 학습자 평균) · 오늘 할 일 · 마지막 AI 검토."""
    return planner.view(db, user, owned(db, m.Project, project_id, user))


@router.post("/projects/{project_id}/plan/review")
def review_plan(project_id: UUID, body: PlanReviewIn, user: CurrentUser, db: DB) -> dict:
    """AI 가 분석표와 내 피드백으로 계획을 검토한다 (20~40초)."""
    project = owned(db, m.Project, project_id, user)
    llm = _llm()
    quota.check(db, user)
    try:
        out = planner.review(db, llm, user, project, body.feedback)
    except planner.PlanError as e:
        db.commit()  # 실패한 호출 기록은 남긴다
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"계획을 검토하지 못했어요. 잠시 후 다시 시도해 주세요 ({e})") from None
    db.commit()
    return out


@router.put("/projects/{project_id}/plan/tasks")
def mark_task(project_id: UUID, body: PlanTaskIn, user: CurrentUser, db: DB) -> dict:
    """오늘 할 일 체크 (레슨처럼 기록으로 알 수 없는 것)."""
    project = owned(db, m.Project, project_id, user)
    planner.mark(db, user, project, body.key, body.done)
    db.commit()
    return planner.view(db, user, project)


# ---------- Deep Dive ----------
class DeepDiveIn(BaseModel):
    retry: bool = False  # 아직 헷갈려요 → 더 잘게 다시


class DeepDivePatch(BaseModel):
    answers: list[int] | None = Field(None, max_length=10)
    feedback: Literal["understood", "confused"] | None = None


@router.get("/problems/{problem_id}/deep-dive", tags=["문제"])
def get_deep_dive(problem_id: str, user: CurrentUser, db: DB) -> dict | None:
    _solved_problem(db, user, problem_id)
    d = deepdive.get(db, user, problem_id)
    return deepdive.out(d) if d else None


@router.post("/problems/{problem_id}/deep-dive", tags=["문제"], status_code=status.HTTP_201_CREATED)
def create_deep_dive(problem_id: str, body: DeepDiveIn, user: CurrentUser, db: DB) -> dict:
    """내 답을 보고 문제를 작은 질문 3~5개로 쪼갠다 (20~40초). 이미 있으면 그대로, retry 면 더 잘게 다시."""
    p = _solved_problem(db, user, problem_id)
    existing = deepdive.get(db, user, problem_id)
    if existing is not None and not body.retry:
        return deepdive.out(existing)
    llm = _llm()
    quota.check(db, user)
    try:
        d = deepdive.create(db, llm, user, p, retry=body.retry)
    except deepdive.DeepDiveError as e:
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Deep Dive 를 만들지 못했어요 ({e})") from None
    db.commit()
    return deepdive.out(d)


@router.patch("/deep-dives/{dive_id}", tags=["문제"])
def save_deep_dive(dive_id: UUID, body: DeepDivePatch, user: CurrentUser, db: DB) -> dict:
    d = owned(db, m.DeepDive, dive_id, user)
    out = deepdive.out(deepdive.save(db, d, body.answers, body.feedback))
    db.commit()
    return out
