"""피드백·문제 신고 (사용자) + 피드백 관리·문제 복구 (운영자)."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select

from education.api.deps import DB, CurrentUser, admin_user
from education.api.dto import AdminFeedbackOut, AdminFeedbackPatch, AnnouncementIn, FeedbackIn, FeedbackOut
from education.db import models as m
from education.services import feedback, notifications

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


# ---------- 운영자 (VOC) ----------
admin = APIRouter(prefix="/admin", tags=["운영"], dependencies=[Depends(admin_user)])


def _admin_view(db, fb: m.Feedback) -> AdminFeedbackOut:
    problem = db.get(m.Problem, fb.problem_id) if fb.problem_id else None
    sender = db.get(m.User, fb.user_id)
    return AdminFeedbackOut(**FeedbackOut.model_validate(fb).model_dump(), user_id=sender.id, user_email=sender.email,
                            user_name=sender.name, problem_hidden=feedback.is_hidden(problem), problem_stem=problem.stem if problem else None)


@admin.get("/feedback")
def list_feedback(db: DB, state: str = "open", kind: str | None = None, q: str | None = None,
                  user_id: UUID | None = None) -> list[AdminFeedbackOut]:
    """state: open(접수+확인 중) · resolved · all. kind 로 종류를, q 로 내용·보낸 사람 이메일을 찾는다."""
    stmt = select(m.Feedback).join(m.User, m.User.id == m.Feedback.user_id).order_by(m.Feedback.created_at.desc()).limit(200)
    if state == "open":
        stmt = stmt.where(m.Feedback.status != "resolved")
    elif state == "resolved":
        stmt = stmt.where(m.Feedback.status == "resolved")
    if kind in feedback.KIND_NAME:
        stmt = stmt.where(m.Feedback.kind == kind)
    if user_id:
        stmt = stmt.where(m.Feedback.user_id == user_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(m.Feedback.message.ilike(like), m.User.email.ilike(like), m.User.name.ilike(like)))
    return [_admin_view(db, f) for f in db.scalars(stmt)]


@admin.get("/feedback/summary")
def feedback_summary(db: DB) -> dict:
    """VOC 현황 — 상태별·종류별 개수 (처리할 것 = 접수 + 확인 중)."""
    by_status = dict(db.execute(select(m.Feedback.status, func.count()).group_by(m.Feedback.status)).all())
    open_kinds = dict(db.execute(select(m.Feedback.kind, func.count()).where(m.Feedback.status != "resolved")
                                 .group_by(m.Feedback.kind)).all())
    return {"by_status": {k: by_status.get(k, 0) for k in ("open", "reviewing", "resolved")},
            "open_by_kind": {k: open_kinds.get(k, 0) for k in feedback.KIND_NAME}}


@admin.patch("/feedback/{feedback_id}")
def update_feedback(feedback_id: UUID, body: AdminFeedbackPatch, db: DB) -> AdminFeedbackOut:
    fb = db.get(m.Feedback, feedback_id)
    if fb is None:
        raise HTTPException(404, "피드백을 찾을 수 없어요")
    if body.status:
        fb.status = body.status
    if body.reply is not None and body.reply.strip() and body.reply.strip() != fb.reply:
        fb.reply, fb.replied_at = body.reply.strip(), datetime.now(timezone.utc)
        notifications.notify(db, fb.user_id, "feedback_reply", f"보내 주신 의견에 답변했어요 · {feedback.KIND_NAME[fb.kind]}",
                             body=f"내 의견: {fb.message[:200]}\n\n답변: {fb.reply}")
    db.commit()
    return _admin_view(db, fb)


@admin.post("/announcements", status_code=status.HTTP_201_CREATED)
def announce(body: AnnouncementIn, db: DB) -> dict:
    """모든 사용자에게 공지 알림."""
    n = notifications.announce(db, body.title.strip(), body=(body.body or "").strip() or None, link=body.link or None)
    db.commit()
    return {"sent": n}


@admin.post("/problems/{problem_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_problem(problem_id: str, db: DB) -> Response:
    """신고로 숨겨진 문제가 실제로는 맞을 때 다시 보이게 한다."""
    problem = db.get(m.Problem, problem_id)
    if problem is None or not feedback.is_hidden(problem):
        raise HTTPException(404, "숨겨진 문제가 아니에요")
    feedback.restore(db, problem)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
