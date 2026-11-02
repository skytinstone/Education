"""피드백·문제 신고 — 두 사람이 신고하면 숨김, 운영자 답변·복구, 메일 알림."""

import pytest
from sqlalchemy import select

from education.config import get_settings
from education.db import models as m
from education.schemas import Domain, ProblemSource, ProblemType, VerificationStatus
from education.services import feedback

PID = "pb_subst"
ADMIN = "admin@example.com"


@pytest.fixture(autouse=True)
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(feedback.mailer, "send_later", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(get_settings(), "admin_emails", f" {ADMIN.upper()} , other-admin@example.com")
    return sent


def report(client, headers, kind="problem", pid=PID, msg="정답이 2번 같아요"):
    return client.post("/api/feedback", json={"kind": kind, "message": msg, "problem_id": pid, "page": "#/chat/x"}, headers=headers)


def test_send_feedback_and_list_mine(client, auth, mails):
    r = client.post("/api/feedback", json={"kind": "feature", "message": "다크 모드가 있으면 좋겠어요"}, headers=auth)
    assert r.status_code == 201 and r.json()["status"] == "open"
    assert [f["message"] for f in client.get("/api/feedback/mine", headers=auth).json()] == ["다크 모드가 있으면 좋겠어요"]
    to, subject, body = mails[0]
    assert to == ADMIN and "기능 제안" in subject and "다크 모드" in body
    assert client.post("/api/feedback", json={"kind": "bug", "message": "x"}, headers=auth).status_code == 422  # 너무 짧음
    assert client.post("/api/feedback", json={"kind": "nope", "message": "내용"}, headers=auth).status_code == 422


def test_two_reporters_hide_problem(client, auth, new_user, db, mails):
    report(client, auth)
    report(client, auth, kind="solution")  # 같은 사람이 여러 번 신고해도 한 명
    assert db.get(m.Problem, PID).verification == VerificationStatus.VERIFIED

    report(client, new_user())
    p = db.get(m.Problem, PID)
    assert p.verification == VerificationStatus.REJECTED and feedback.is_hidden(p)
    assert "자동으로 숨김" in mails[-1][2]
    # 다른 학생에게 더는 나가지 않는다
    assert PID not in {x["id"] for x in client.get("/api/sync", headers=new_user()).json()["problems"]}


def test_review_or_feature_kind_does_not_hide(client, auth, new_user, db):
    report(client, auth, kind="review")
    report(client, new_user(), kind="feature")
    assert db.get(m.Problem, PID).verification == VerificationStatus.VERIFIED


def test_admin_only(client, auth, new_user):
    assert client.get("/api/admin/feedback", headers=auth).status_code == 404  # 일반 사용자에겐 없는 경로처럼
    assert client.get("/api/sync", headers=auth).json()["user"]["isAdmin"] is False
    admin = new_user(email=ADMIN)
    assert client.get("/api/sync", headers=admin).json()["user"]["isAdmin"] is True
    assert client.get("/api/admin/feedback", headers=admin).status_code == 200


def test_admin_reply_and_restore(client, auth, new_user, db):
    report(client, auth)
    report(client, new_user())
    admin = new_user(email=ADMIN)
    items = client.get("/api/admin/feedback", headers=admin).json()
    assert len(items) == 2 and items[0]["problem_hidden"] is True and items[0]["problem_stem"]
    my_email = client.get("/api/me", headers=auth).json()["email"]
    fid = next(i["id"] for i in items if i["user_email"] == my_email)
    r = client.patch(f"/api/admin/feedback/{fid}", json={"status": "reviewing", "reply": "확인하고 있어요"}, headers=admin).json()
    assert r["status"] == "reviewing" and r["reply"] == "확인하고 있어요" and r["replied_at"]
    mine = client.get("/api/feedback/mine", headers=auth).json()[0]
    assert mine["reply"] == "확인하고 있어요"

    assert client.post(f"/api/admin/problems/{PID}/restore", headers=admin).status_code == 204
    p = db.get(m.Problem, PID)
    assert p.verification == VerificationStatus.VERIFIED and not feedback.is_hidden(p)
    assert client.get("/api/admin/feedback", headers=admin).json() == []  # 그 문제의 신고는 해결 처리
    assert client.post(f"/api/admin/problems/{PID}/restore", headers=admin).status_code == 404  # 이미 보임


def test_cannot_attach_someone_elses_private_problem(client, auth, new_user, db):
    other = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    db.add(m.Problem(id="private_fb", domain=Domain.MATH, difficulty=3, problem_type=ProblemType.MULTIPLE_CHOICE, stem="비공개",
                     choices=["1", "2", "3", "4", "5"], answer="1", solution="-", source=ProblemSource.PAST_EXAM,
                     owner_user_id=other.id))
    db.flush()
    r = report(client, new_user(), pid="private_fb")
    assert r.status_code == 201 and r.json()["problem_id"] is None
    assert report(client, auth, pid="nope").status_code == 404
