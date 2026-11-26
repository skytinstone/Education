"""사람 검토 큐 (Human-in-the-loop) — 자동 검사로는 확신할 수 없는 문제를 운영자가 판정한다.

들어오는 곳
- report      학생이 문제·정답·해설 오류를 신고했을 때 (services/feedback.py)
- item_stats  문제 성적표에서 D 등급이거나 '정답 의심' 표시가 붙었을 때 (services/item_stats.py)
- math_check  검증은 통과했지만 계산 도구 검산 에이전트가 실패해 계산을 확인하지 못했을 때 (services/generator.py)

판정
- keep  문제가 맞다 → 보이게 두고 (신고로 숨겨졌으면 복구), 열린 신고는 해결
- fix   정답이 틀렸다 → 정답 번호를 고치고 보이게 둔다
- hide  문제가 잘못됐다 → 숨긴다 (verification = rejected)

데이터 플라이휠: 판정한 객관식 문제는 평가 골든셋 'reviewed' 로 자동으로 들어간다 (reviewed_cases).
keep → 좋은 문제, fix → 원래 정답 = 망가진 문제(wrong_key) + 고친 정답 = 좋은 문제, hide → 망가진 문제(reviewed_bad).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.db import models as m
from education.schemas import VerificationStatus

SOURCE_NAME = {"report": "학생 신고", "item_stats": "문제 성적표", "math_check": "검산 확인 필요"}


def enqueue(db: Session, problem_id: str, source: str, reason: str) -> bool:
    """검토 큐에 넣는다. 이미 열린 항목이 있으면 건너뛴다 (True: 새로 넣음)."""
    res = db.execute(insert(m.ReviewItem).values(problem_id=problem_id, source=source, reason=reason[:1000])
                     .on_conflict_do_nothing(index_elements=["problem_id"], index_where=m.ReviewItem.status == "open"))
    db.flush()
    return bool(res.rowcount)


def decide(db: Session, item: m.ReviewItem, admin: m.User, action: str, *, answer: str | None = None, note: str = "") -> m.ReviewItem:
    if item.status != "open":
        raise ValueError("이미 판정한 항목이에요")
    p = db.get(m.Problem, item.problem_id)
    item.answer_before = p.answer
    if action == "fix":
        if not answer or (p.choices and not (answer.isdigit() and 1 <= int(answer) <= len(p.choices))):
            raise ValueError("고칠 정답을 골라 주세요")
        p.answer = answer
        item.answer_after = answer
    if action in ("keep", "fix"):
        meta = dict(p.generation_meta or {})
        meta.pop("hidden_by_reports", None)
        meta.pop("hidden_by_review", None)
        p.generation_meta = meta or None
        p.verification = VerificationStatus.VERIFIED
        for fb in db.scalars(select(m.Feedback).where(m.Feedback.problem_id == p.id, m.Feedback.status != "resolved")):
            fb.status = "resolved"
    elif action == "hide":
        p.verification = VerificationStatus.REJECTED
        p.generation_meta = {**(p.generation_meta or {}), "hidden_by_review": True}
    else:
        raise ValueError("판정은 keep · fix · hide 중 하나예요")
    item.status, item.note, item.decided_by, item.decided_at = action, note[:1000], admin.id, func.now()
    db.flush()
    return item


def counts(db: Session) -> dict:
    return dict(db.execute(select(m.ReviewItem.status, func.count()).group_by(m.ReviewItem.status)).all())


def reviewed_cases(db: Session) -> list[dict]:
    """판정한 객관식 문제 → 평가 골든셋 형식 (harness/evals 의 verify 와 같은 모양)."""
    rows = db.execute(select(m.ReviewItem, m.Problem).join(m.Problem, m.Problem.id == m.ReviewItem.problem_id)
                      .where(m.ReviewItem.status != "open", m.Problem.choices.is_not(None))
                      .order_by(m.ReviewItem.decided_at)).all()
    out: list[dict] = []
    for it, p in rows:
        if not p.choices or len(p.choices) != 5:
            continue  # 평가는 5지선다 형식으로 돈다
        base = {"domain": p.domain, "stem": p.stem, "choices": list(p.choices)}
        if it.status == "keep":
            out.append({**base, "id": f"rv_{it.id.hex[:8]}", "label": "good", "answer": it.answer_before})
        elif it.status == "fix":
            out.append({**base, "id": f"rv_{it.id.hex[:8]}_fixed", "label": "good", "answer": it.answer_after})
            out.append({**base, "id": f"rv_{it.id.hex[:8]}_before", "label": "bad", "defect": "wrong_key", "answer": it.answer_before})
        else:
            out.append({**base, "id": f"rv_{it.id.hex[:8]}", "label": "bad", "defect": "reviewed_bad", "answer": it.answer_before})
    return out
