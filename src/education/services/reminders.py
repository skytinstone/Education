"""하루 한 번 계산하는 학습 알림 — 복습(간격 반복)·시험 D-day·암기 카드 (아침), 연속 학습 (저녁).

알림마다 key 를 붙여 같은 날(카드는 같은 주) 여러 번 돌려도 한 번만 만든다.
서버 cron 이 python -m education.reminders [--evening] 으로 부른다 (docs/DEPLOY.md).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.services import learning, notifications

REVIEW_DAYS = (1, 3, 7)  # 틀린 지 며칠째에 다시 풀지
DDAY_TIPS = {
    30: "한 달 남았어요. 약한 개념부터 정리해 보세요",
    7: "일주일 남았어요. 오답노트를 한 번 더 훑어보세요",
    1: "내일이 시험이에요. 새 문제보다 틀렸던 문제와 암기 카드를 복습해요",
    0: "긴장 풀고, 아는 것부터 차근차근. 응원해요",
}
CARDS_MIN = 5
STREAK_MIN = 3


def _local_date(column):
    return func.date(func.timezone(get_settings().timezone, column))


def review_due(db: Session, user: m.User, today: date) -> bool:
    days = [today - timedelta(days=d) for d in REVIEW_DAYS]
    n = db.scalar(select(func.count()).where(
        m.WrongNote.user_id == user.id, m.WrongNote.resolved_at.is_(None), _local_date(m.WrongNote.created_at).in_(days)))
    if not n:
        return False
    notifications.notify(db, user.id, "review_due", f"복습할 시간 · 오답 {n}문제",
                         body="틀린 지 1·3·7일째에 다시 풀면 훨씬 오래 기억돼요", link="#/notes", key=f"review:{today}")
    return True


def exam_dday(db: Session, user: m.User, today: date) -> int:
    targets = [today + timedelta(days=d) for d in DDAY_TIPS]
    sent = 0
    for p in db.scalars(select(m.Project).where(m.Project.user_id == user.id, m.Project.exam_date.in_(targets))):
        n = (p.exam_date - today).days
        notifications.notify(db, user.id, "exam_dday", f"오늘 시험이에요 · {p.name}" if n == 0 else f"시험 D-{n} · {p.name}",
                             body=DDAY_TIPS[n], link=f"#/project/{p.id}", key=f"dday:{p.id}:{p.exam_date}:{n}")
        sent += 1
    return sent


def cards_due(db: Session, user: m.User, today: date) -> bool:
    n = db.scalar(select(func.count()).where(m.Card.user_id == user.id, m.Card.known.is_not(True)))
    if n < CARDS_MIN:
        return False
    year, week, _ = today.isocalendar()
    notifications.notify(db, user.id, "cards_due", f"외울 암기 카드 {n}장이 남았어요",
                         body="하루 5분이면 충분해요. 모르는 카드부터 넘겨 봐요", link="#/library/cards", key=f"cards:{year}-W{week}")
    return True


def streak_at_risk(db: Session, user: m.User, today: date) -> bool:
    """어제까지 STREAK_MIN 일 넘게 이어 왔는데 오늘 아직 안 풀었으면."""
    since = datetime.now(timezone.utc) - timedelta(days=400)
    days = set(db.scalars(select(_local_date(m.Attempt.created_at)).distinct().where(
        m.Attempt.user_id == user.id, m.Attempt.created_at >= since)))
    if today in days:
        return False
    n, d = 0, today - timedelta(days=1)
    while d in days:
        n, d = n + 1, d - timedelta(days=1)
    if n < STREAK_MIN:
        return False
    notifications.notify(db, user.id, "streak", f"{n}일 연속 학습이 끊기기 전에",
                         body="오늘 한 문제만 풀어도 기록이 이어져요", link="#/", key=f"streak:{today}")
    return True


def run(db: Session, *, evening: bool = False, today: date | None = None) -> Counter:
    """모든 사용자에게 오늘의 알림을 만든다. 돌려주는 값: 종류별로 알림을 받을 사용자 수."""
    today = today or learning.local_today(db)
    sent: Counter = Counter()
    for user in db.scalars(select(m.User)):
        if evening:
            sent["streak"] += streak_at_risk(db, user, today)
        else:
            sent["review_due"] += review_due(db, user, today)
            sent["exam_dday"] += exam_dday(db, user, today)
            sent["cards_due"] += cards_due(db, user, today)
    db.commit()
    return sent
