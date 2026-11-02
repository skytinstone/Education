"""하루 한 번 학습 알림 — 복습(1·3·7일), 시험 D-day, 암기 카드(주 1회), 연속 학습(저녁), 중복 방지."""

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

import pytest

from education.config import get_settings
from education.db import models as m
from education.services import reminders

TODAY = date(2026, 11, 10)  # 화요일


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setattr(get_settings(), "timezone", "UTC")


def at(d: date, hour=9) -> datetime:
    return datetime.combine(d, time(hour), tzinfo=timezone.utc)


def user_of(client, headers, db) -> m.User:
    return db.get(m.User, UUID(client.get("/api/me", headers=headers).json()["id"]))


def kinds(client, headers):
    return sorted((n["kind"], n["title"]) for n in client.get("/api/notifications", headers=headers).json()["items"])


def test_review_due_on_day_1_3_7(client, auth, db):
    u = user_of(client, auth, db)
    for pid, ago in (("pb_subst", 1), ("pb_log", 3), ("pb_defint", 7), ("pb_seq", 2)):
        db.add(m.WrongNote(user_id=u.id, problem_id=pid, answer="1", created_at=at(TODAY - timedelta(days=ago))))
    db.add(m.WrongNote(user_id=u.id, problem_id="pb_cond", answer="1", created_at=at(TODAY - timedelta(days=3)),
                       resolved_at=at(TODAY)))  # 이미 극복한 오답은 빼기
    db.flush()
    reminders.run(db, today=TODAY)
    reminders.run(db, today=TODAY)  # 다시 돌려도 한 번만
    assert kinds(client, auth) == [("review_due", "복습할 시간 · 오답 3문제")]


def test_exam_dday(client, auth, db):
    u = user_of(client, auth, db)
    for name, d in (("D7", 7), ("D1", 1), ("오늘", 0), ("D5", 5)):
        db.add(m.Project(user_id=u.id, name=name, subject_id="math.calculus", exam_date=TODAY + timedelta(days=d)))
    db.flush()
    sent = reminders.run(db, today=TODAY)
    assert sent["exam_dday"] == 3
    titles = [t for k, t in kinds(client, auth) if k == "exam_dday"]
    assert sorted(titles) == ["시험 D-1 · D1", "시험 D-7 · D7", "오늘 시험이에요 · 오늘"]


def test_cards_due_weekly(client, auth, db):
    u = user_of(client, auth, db)
    for i in range(5):
        db.add(m.Card(user_id=u.id, concept_id="math.calculus.int_methods.substitution_parts", front=f"Q{i}", back="A",
                      known=None if i else False))
    db.add(m.Card(user_id=u.id, concept_id="math.calculus.int_methods.substitution_parts", front="외움", back="A", known=True))
    db.flush()
    reminders.run(db, today=TODAY)
    reminders.run(db, today=TODAY + timedelta(days=2))  # 같은 주
    assert kinds(client, auth) == [("cards_due", "외울 암기 카드 5장이 남았어요")]
    reminders.run(db, today=TODAY + timedelta(days=7))  # 다음 주
    assert len(kinds(client, auth)) == 2


def test_streak_reminder_in_evening(client, auth, new_user, db):
    u = user_of(client, auth, db)
    for ago in (1, 2, 3):
        db.add(m.Attempt(user_id=u.id, problem_id="pb_subst", answer="1", correct=True, created_at=at(TODAY - timedelta(days=ago))))
    done = new_user()  # 오늘 이미 푼 사람
    v = user_of(client, done, db)
    for ago in (0, 1, 2, 3):
        db.add(m.Attempt(user_id=v.id, problem_id="pb_subst", answer="1", correct=True, created_at=at(TODAY - timedelta(days=ago))))
    db.flush()
    assert reminders.run(db, today=TODAY)["streak"] == 0  # 아침에는 안 보냄
    reminders.run(db, evening=True, today=TODAY)
    assert kinds(client, auth) == [("streak", "3일 연속 학습이 끊기기 전에")]
    assert kinds(client, done) == []


def test_nothing_for_new_user(client, auth, db):
    sent = reminders.run(db, today=TODAY)
    assert sum(sent.values()) == 0 and kinds(client, auth) == []
