"""운영 콘솔 — 가입·이용 현황, AI 사용량, 로그인 기록, 계정 정지·삭제, VOC 필터."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from education.config import get_settings
from education.db import models as m
from education.services import audit, feedback

from conftest import signup

ADMIN = "admin@example.com"


@pytest.fixture(autouse=True)
def admins(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)
    monkeypatch.setattr(feedback.mailer, "send_later", lambda *a: None)


@pytest.fixture
def admin(client) -> dict:
    return signup(client, name="운영자", email=ADMIN)


def user_id(client, headers) -> str:
    return client.get("/api/me", headers=headers).json()["id"]


def test_admin_page_and_landing_are_served(client):
    page = client.get("/admin")
    assert page.status_code == 200 and "관리자 로그인" in page.text and page.headers["x-robots-tag"] == "noindex"
    landing = client.get("/").text
    assert 'property="og:image" content="https://eurekai.cloud/app/og-image.png?v=3"' in landing  # 링크드인·카톡 미리보기
    assert client.get("/app/og-image.png").headers["content-type"] == "image/png"


def test_admin_paths_hidden_from_users(client, auth):
    for path in ("/api/admin/overview", "/api/admin/ai-usage", "/api/admin/logins", "/api/admin/users"):
        assert client.get(path, headers=auth).status_code == 404, path


def test_overview_counts_signups_methods_and_activity(client, admin, new_user, db):
    alice = new_user(email="alice@example.com")
    client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "3"}, headers=alice)
    db.add(m.LLMCall(purpose="generate", model="gpt-x", ok=True, cost_usd=0.25, input_tokens=100, output_tokens=50,
                     user_id=db.scalar(select(m.User.id).where(m.User.email == "alice@example.com"))))
    db.add(m.LLMCall(purpose="verify", model="gpt-x", ok=False, error="timeout"))
    db.flush()

    o = client.get("/api/admin/overview", headers=admin).json()
    assert o["users"]["total"] >= 2 and o["users"]["new_today"] >= 2
    assert o["sign_in_methods"]["password"] >= 2
    assert o["active"]["dau"] >= 2  # 가입하면서 로그인한 두 사람
    assert o["signups_by_day"][-1]["count"] >= 2 and len(o["signups_by_day"]) == 30
    assert o["ai"]["cost_today"] >= 0.25 and o["ai"]["failed_30d"] >= 1


def test_ai_usage_breakdown(client, admin, auth, db):
    uid = user_id(client, auth)
    for purpose, cost in (("generate", 0.1), ("generate", 0.2), ("verify", 0.05)):
        db.add(m.LLMCall(purpose=purpose, model="gpt-x", ok=True, cost_usd=cost, input_tokens=10, output_tokens=5, user_id=uid))
    db.add(m.LLMCall(purpose="verify", model="gpt-x", ok=False, error="rate limit", user_id=uid))
    db.flush()

    r = client.get("/api/admin/ai-usage?days=7", headers=admin).json()
    assert r["totals"]["calls"] >= 4 and r["totals"]["failed"] >= 1 and r["totals"]["cost_usd"] >= 0.35
    gen = next(p for p in r["by_purpose"] if p["key"] == "generate")
    assert gen["calls"] >= 2 and gen["cost_usd"] >= 0.3
    assert len(r["by_day"]) == 7
    assert r["top_users"][0]["user_id"] == uid
    assert any(e["error"] == "rate limit" for e in r["recent_errors"])


def test_login_events_success_failure_and_filters(client, admin):
    signup(client, email="bob@example.com", password="right-pass1")
    assert client.post("/api/auth/login", json={"email": "bob@example.com", "password": "wrong-pass1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "Nobody@example.com", "password": "x1234567"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "bob@example.com", "password": "right-pass1"}).status_code == 200

    r = client.get("/api/admin/logins?q=bob@", headers=admin).json()
    kinds = [(e["kind"], e["ok"], e["reason"]) for e in r["items"]]
    assert kinds == [("login", True, None), ("login", False, "bad_credentials"), ("signup", True, None)]  # 최신순
    assert all(e["method"] == "password" for e in r["items"])
    # 없는 이메일로 실패한 시도도 남는다 (소문자로)
    fails = client.get("/api/admin/logins?result=fail", headers=admin).json()["items"]
    assert any(e["email"] == "nobody@example.com" and e["user_id"] is None for e in fails)
    assert r["last_24h"]["failed"] >= 2


def test_old_login_events_are_purged(client, admin, auth, db):
    old = m.LoginEvent(method="password", ok=True, email="old@example.com",
                       created_at=datetime.now(timezone.utc) - timedelta(days=audit.RETENTION_DAYS + 1))
    db.add(old)
    db.flush()
    items = client.get("/api/admin/logins?q=old@", headers=admin).json()["items"]
    assert items == [] and db.get(m.LoginEvent, old.id) is None


def test_user_list_and_detail(client, admin, new_user):
    carol = new_user(name="캐롤", email="carol@example.com")
    client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "1"}, headers=carol)
    client.post("/api/feedback", json={"kind": "bug", "message": "버튼이 안 눌려요"}, headers=carol)

    r = client.get("/api/admin/users?q=carol", headers=admin).json()
    assert r["total"] == 1
    row = r["items"][0]
    assert row["name"] == "캐롤" and row["methods"] == ["password"] and row["attempts"] == 1 and row["last_login_at"]

    d = client.get(f"/api/admin/users/{row['id']}", headers=admin).json()
    assert d["learning"]["attempts"] == 1 and d["learning"]["open_notes"] == 1
    assert d["logins"][0]["kind"] == "signup"
    assert d["feedback"][0]["message"] == "버튼이 안 눌려요"
    assert client.get("/api/admin/users/00000000-0000-0000-0000-000000000000", headers=admin).status_code == 404


def test_suspend_blocks_existing_token_and_login(client, admin, db):
    headers = signup(client, email="dave@example.com", password="dave-pass1")
    uid = user_id(client, headers)

    assert client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "x"}, headers=admin).status_code == 422  # 이유가 너무 짧음
    r = client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "다른 사람 문제 무단 업로드"}, headers=admin)
    assert r.status_code == 200 and r.json()["user"]["suspended_reason"] == "다른 사람 문제 무단 업로드"

    assert client.get("/api/sync", headers=headers).status_code == 401  # 이미 받은 토큰도 막힘
    res = client.post("/api/auth/login", json={"email": "dave@example.com", "password": "dave-pass1"})
    assert res.status_code == 403 and "정지" in res.json()["detail"]
    ev = db.scalars(select(m.LoginEvent).where(m.LoginEvent.email == "dave@example.com").order_by(m.LoginEvent.created_at.desc())).first()
    assert ev.ok is False and ev.reason == "suspended"
    assert client.get("/api/admin/users?state=suspended", headers=admin).json()["total"] >= 1

    client.post(f"/api/admin/users/{uid}/unsuspend", headers=admin)
    assert client.post("/api/auth/login", json={"email": "dave@example.com", "password": "dave-pass1"}).status_code == 200


def test_admin_accounts_are_protected_and_delete_needs_email(client, admin, db):
    admin_id = user_id(client, admin)
    assert client.post(f"/api/admin/users/{admin_id}/suspend", json={"reason": "실수"}, headers=admin).status_code == 409
    assert client.request("DELETE", f"/api/admin/users/{admin_id}", json={"confirm_email": ADMIN}, headers=admin).status_code == 409

    victim = signup(client, email="erin@example.com")
    uid = user_id(client, victim)
    assert client.request("DELETE", f"/api/admin/users/{uid}", json={"confirm_email": "wrong@example.com"}, headers=admin).status_code == 422
    assert client.request("DELETE", f"/api/admin/users/{uid}", json={"confirm_email": "ERIN@example.com"}, headers=admin).status_code == 204
    assert db.scalar(select(m.User).where(m.User.email == "erin@example.com")) is None
    assert client.get("/api/sync", headers=victim).status_code == 401


def test_voc_filters_and_summary(client, admin, new_user):
    frank = new_user(name="프랭크", email="frank@example.com")
    client.post("/api/feedback", json={"kind": "feature", "message": "다크 모드 주세요"}, headers=frank)
    client.post("/api/feedback", json={"kind": "bug", "message": "로그인이 풀려요"}, headers=frank)

    bugs = client.get("/api/admin/feedback?state=all&kind=bug", headers=admin).json()
    assert [f["message"] for f in bugs] == ["로그인이 풀려요"] and bugs[0]["user_name"] == "프랭크"
    assert [f["message"] for f in client.get("/api/admin/feedback?state=all&q=다크", headers=admin).json()] == ["다크 모드 주세요"]
    assert len(client.get("/api/admin/feedback?state=all&q=frank@", headers=admin).json()) == 2

    s = client.get("/api/admin/feedback/summary", headers=admin).json()
    assert s["by_status"]["open"] >= 2 and s["open_by_kind"]["bug"] >= 1
