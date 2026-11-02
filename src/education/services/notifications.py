"""알림 만들기 · 읽음 처리.

notify() 는 커밋하지 않는다 — 알림을 만든 쪽의 변경과 함께 커밋해서, 일은 실패했는데 알림만 남는 일이 없게 한다.
key 가 같은 알림은 사용자마다 한 번만 만든다 (하루 한 번 도는 알림이 중복되지 않게).
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.db import models as m


def notify(db: Session, user_id: uuid.UUID, kind: str, title: str, *, body: str | None = None, link: str | None = None,
           key: str | None = None) -> None:
    stmt = insert(m.Notification).values(user_id=user_id, kind=kind, title=title[:120], body=body, link=link, key=key)
    db.execute(stmt.on_conflict_do_nothing(constraint="uq_notification_user_key") if key else stmt)


def announce(db: Session, title: str, *, body: str | None = None, link: str | None = None) -> int:
    """모든 사용자에게 같은 공지 (한 번의 INSERT … SELECT)."""
    rows = select(m.User.id, literal("announcement", String), literal(title[:120], String), literal(body, Text),
                  literal(link, String))
    db.execute(insert(m.Notification).from_select(["user_id", "kind", "title", "body", "link"], rows))
    return db.scalar(select(func.count()).select_from(m.User))  # INSERT … SELECT 는 행 수를 돌려주지 않는다


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(m.Notification.user_id == user_id, m.Notification.read_at.is_(None)))


def recent(db: Session, user_id: uuid.UUID, limit: int = 30) -> list[m.Notification]:
    q = select(m.Notification).where(m.Notification.user_id == user_id).order_by(m.Notification.created_at.desc()).limit(limit)
    return list(db.scalars(q))


def mark_read(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID] | None) -> None:
    q = update(m.Notification).where(m.Notification.user_id == user_id, m.Notification.read_at.is_(None))
    if ids is not None:
        q = q.where(m.Notification.id.in_(ids))
    db.execute(q.values(read_at=func.now()))
