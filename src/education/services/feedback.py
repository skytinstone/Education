"""피드백·문제 신고.

문제 신고(정답·문제 오류, 해설 오류)는 같은 공용 문제를 서로 다른 두 사람이 하면 그 문제를 숨긴다
(verification → rejected, generation_meta.hidden_by_reports). 운영자가 확인하고 복구할 수 있다.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.schemas import VerificationStatus
from education.services import mailer

REPORT_KINDS = ("problem", "solution")
HIDE_AFTER = 2  # 서로 다른 신고자 수
KIND_NAME = {"problem": "문제·정답 오류", "solution": "해설 오류", "review": "서술형 채점 이상", "feature": "기능 제안",
             "bug": "버그", "other": "기타"}


def is_hidden(problem: m.Problem | None) -> bool:
    return bool(problem and (problem.generation_meta or {}).get("hidden_by_reports"))


def submit(db: Session, user: m.User, *, kind: str, message: str, problem_id: str | None, page: str | None) -> m.Feedback:
    problem = db.get(m.Problem, problem_id) if problem_id else None
    if problem is not None and problem.owner_user_id not in (None, user.id):
        problem = None  # 남의 비공개 문제는 연결하지 않는다
    fb = m.Feedback(user_id=user.id, kind=kind, message=message.strip(), problem_id=problem.id if problem else None,
                    page=page)
    db.add(fb)
    db.flush()
    hidden = problem is not None and kind in REPORT_KINDS and _maybe_hide(db, problem)
    db.commit()

    s = get_settings()
    to = s.feedback_notify_email or next(iter(sorted(s.admins)), None)
    lines = [f"종류: {KIND_NAME[kind]}", f"보낸 사람: {user.name} <{user.email}>", f"화면: {page or '-'}"]
    if problem:
        lines += [f"문제: {problem.id}" + (" (신고가 쌓여 자동으로 숨김)" if hidden else ""), f"  {problem.stem[:200]}"]
    mailer.send_later(to, f"[Eureka 피드백] {KIND_NAME[kind]}", "\n".join(lines) + f"\n\n{fb.message}\n\n— {s.public_base_url}")
    return fb


def _maybe_hide(db: Session, problem: m.Problem) -> bool:
    if problem.owner_user_id is not None or problem.verification != VerificationStatus.VERIFIED or is_hidden(problem):
        return False
    reporters = db.scalar(select(func.count(func.distinct(m.Feedback.user_id))).where(
        m.Feedback.problem_id == problem.id, m.Feedback.kind.in_(REPORT_KINDS), m.Feedback.status != "resolved"))
    if reporters < HIDE_AFTER:
        return False
    problem.verification = VerificationStatus.REJECTED
    problem.generation_meta = {**(problem.generation_meta or {}), "hidden_by_reports": True}
    return True


def restore(db: Session, problem: m.Problem) -> None:
    """운영자가 확인해 보니 문제가 맞을 때 — 다시 보이게 하고, 그 문제의 열린 신고는 해결 처리."""
    meta = dict(problem.generation_meta or {})
    meta.pop("hidden_by_reports", None)
    problem.generation_meta = meta or None
    problem.verification = VerificationStatus.VERIFIED
    for fb in db.scalars(select(m.Feedback).where(m.Feedback.problem_id == problem.id, m.Feedback.status != "resolved")):
        fb.status = "resolved"
    db.commit()
