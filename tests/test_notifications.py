"""알림 — 기출 분석 완료, 피드백 답변, 공지, 읽음 처리, 중복 방지."""

import pytest
from sqlalchemy import select

from education.config import get_settings
from education.db import models as m
from education.services import feedback, notifications

ADMIN = "admin@example.com"


@pytest.fixture(autouse=True)
def no_mail(monkeypatch):
    monkeypatch.setattr(feedback.mailer, "send_later", lambda *a: None)
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)


def db_user_id(client, headers):
    return client.get("/api/me", headers=headers).json()["id"]


def test_list_and_mark_read(client, auth, db):
    uid = db_user_id(client, auth)
    for i in range(3):
        notifications.notify(db, uid, "announcement", f"공지 {i}")
    db.flush()
    r = client.get("/api/notifications", headers=auth).json()
    assert r["unread"] == 3 and len(r["items"]) == 3
    assert client.get("/api/sync", headers=auth).json()["user"]["unreadNotifications"] == 3

    first = r["items"][0]["id"]
    assert client.post("/api/notifications/read", json={"ids": [first]}, headers=auth).status_code == 204
    r = client.get("/api/notifications", headers=auth).json()
    assert r["unread"] == 2 and next(n for n in r["items"] if n["id"] == first)["read_at"]
    client.post("/api/notifications/read", json={}, headers=auth)
    assert client.get("/api/notifications", headers=auth).json()["unread"] == 0


def test_notifications_are_private(client, auth, new_user, db):
    notifications.notify(db, db_user_id(client, auth), "announcement", "나만")
    db.flush()
    other = new_user()
    assert client.get("/api/notifications", headers=other).json()["items"] == []
    mine = client.get("/api/notifications", headers=auth).json()["items"][0]["id"]
    client.post("/api/notifications/read", json={"ids": [mine]}, headers=other)  # 남의 알림은 못 읽음 처리
    assert client.get("/api/notifications", headers=auth).json()["unread"] == 1


def test_same_key_only_once(client, auth, db):
    uid = db_user_id(client, auth)
    for _ in range(3):
        notifications.notify(db, uid, "exam_dday", "시험 D-7", key="dday:p1:7")
    notifications.notify(db, uid, "exam_dday", "시험 D-1", key="dday:p1:1")
    db.flush()
    assert client.get("/api/notifications", headers=auth).json()["unread"] == 2


def test_feedback_reply_notifies_user(client, auth, new_user):
    fid = client.post("/api/feedback", json={"kind": "feature", "message": "다크 모드 주세요"}, headers=auth).json()["id"]
    admin = new_user(email=ADMIN)
    client.patch(f"/api/admin/feedback/{fid}", json={"reply": "다음 업데이트에 넣을게요", "status": "resolved"}, headers=admin)
    client.patch(f"/api/admin/feedback/{fid}", json={"reply": "다음 업데이트에 넣을게요"}, headers=admin)  # 같은 답변은 다시 알리지 않음
    items = client.get("/api/notifications", headers=auth).json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "feedback_reply" and "다음 업데이트에 넣을게요" in items[0]["body"]


def test_announcement_to_everyone(client, auth, new_user):
    other = new_user()
    admin = new_user(email=ADMIN)
    r = client.post("/api/admin/announcements", json={"title": "점검 안내", "body": "오늘 밤 10시", "link": "#/"}, headers=admin)
    assert r.status_code == 201 and r.json()["sent"] >= 3
    for h in (auth, other, admin):
        n = client.get("/api/notifications", headers=h).json()["items"][0]
        assert (n["kind"], n["title"], n["body"], n["link"]) == ("announcement", "점검 안내", "오늘 밤 10시", "#/")
    assert client.post("/api/admin/announcements", json={"title": "x"}, headers=auth).status_code == 404  # 운영자만


def test_material_done_notifies(client, auth, db, monkeypatch, tmp_path):
    from contextlib import contextmanager

    from education.services import materials
    from education.services.llm import LLMError
    monkeypatch.setattr(materials, "UPLOAD_DIR", tmp_path)

    class Failing:
        def structured(self, **kw):
            raise LLMError("timeout")

    pid = client.post("/api/projects", json={"name": "수능", "subject_id": "math.calculus"}, headers=auth).json()["id"]
    user = db.scalar(select(m.User).where(m.User.id == db_user_id(client, auth)))
    mat = materials.save_upload(user, db.get(m.Project, pid), "6월 모평.pdf", "application/pdf", b"%PDF-1.4", True)
    db.add(mat)
    db.flush()

    @contextmanager
    def same_session():
        yield db

    materials.process(mat.id, same_session, llm=Failing())
    n = client.get("/api/notifications", headers=auth).json()["items"][0]
    assert n["kind"] == "material" and "실패" in n["title"] and n["link"] == f"#/project/{pid}"
