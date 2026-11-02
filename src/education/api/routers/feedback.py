"""피드백·문제 신고 (사용자) + 피드백 관리·문제 복구 (운영자)."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from education.api.deps import DB, CurrentUser
from education.api.dto import AdminFeedbackOut, AdminFeedbackPatch, FeedbackIn, FeedbackOut
from education.config import get_settings
from education.db import models as m
from education.services import feedback

router = APIRouter(tags=["피드백"])


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def send_feedback(body: FeedbackIn, user: CurrentUser, db: DB) -> FeedbackOut:
    """의견 보내기. 문제 신고(problem·solution)는 같은 문제를 두 사람이 신고하면 그 문제를 숨긴다."""
    if body.problem_id and db.get(m.Problem, body.problem_id) is None:
        raise HTTPException(404, "문제를 찾을 수 없어요")
    fb = feedback.submit(db, user, kind=body.kind, message=body.message, problem_id=body.problem_id, page=body.page)
    return FeedbackOut.model_validate(fb)


@router.get("/feedback/mine")
def my_feedback(user: CurrentUser, db: DB) -> list[FeedbackOut]:
    q = select(m.Feedback).where(m.Feedback.user_id == user.id).order_by(m.Feedback.created_at.desc()).limit(50)
    return [FeedbackOut.model_validate(f) for f in db.scalars(q)]


# ---------- 운영자 ----------
def admin_user(user: CurrentUser) -> m.User:
    if user.email.lower() not in get_settings().admins:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "찾을 수 없어요")  # 운영자 경로가 있다는 것도 알리지 않음
    return user


admin = APIRouter(prefix="/admin", tags=["운영"], dependencies=[Depends(admin_user)])


def _admin_view(db, fb: m.Feedback) -> AdminFeedbackOut:
    problem = db.get(m.Problem, fb.problem_id) if fb.problem_id else None
    return AdminFeedbackOut(**FeedbackOut.model_validate(fb).model_dump(), user_email=db.get(m.User, fb.user_id).email,
                            problem_hidden=feedback.is_hidden(problem), problem_stem=problem.stem if problem else None)


@admin.get("/feedback")
def list_feedback(db: DB, state: str = "open") -> list[AdminFeedbackOut]:
    """state: open(접수+확인 중) · resolved · all"""
    q = select(m.Feedback).order_by(m.Feedback.created_at.desc()).limit(200)
    if state == "open":
        q = q.where(m.Feedback.status != "resolved")
    elif state == "resolved":
        q = q.where(m.Feedback.status == "resolved")
    return [_admin_view(db, f) for f in db.scalars(q)]


@admin.patch("/feedback/{feedback_id}")
def update_feedback(feedback_id: UUID, body: AdminFeedbackPatch, db: DB) -> AdminFeedbackOut:
    fb = db.get(m.Feedback, feedback_id)
    if fb is None:
        raise HTTPException(404, "피드백을 찾을 수 없어요")
    if body.status:
        fb.status = body.status
    if body.reply is not None and body.reply.strip():
        fb.reply, fb.replied_at = body.reply.strip(), datetime.now(timezone.utc)
    db.commit()
    return _admin_view(db, fb)


@admin.post("/problems/{problem_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_problem(problem_id: str, db: DB) -> Response:
    """신고로 숨겨진 문제가 실제로는 맞을 때 다시 보이게 한다."""
    problem = db.get(m.Problem, problem_id)
    if problem is None or not feedback.is_hidden(problem):
        raise HTTPException(404, "숨겨진 문제가 아니에요")
    feedback.restore(db, problem)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
