"""운영 콘솔 '회원' — 실시간 접속 상태와 접속 IP."""

from datetime import datetime, timedelta, timezone

import pytest

from education.config import get_settings
from education.db import models as m
from education.services import audit

from conftest import signup

ADMIN = "admin@example.com"


@pytest.fixture(autouse=True)
def admins(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)


@pytest.fixture
def admin(client) -> dict:
    return signup(client, name="운영자", email=ADMIN)


def uid(client, headers) -> str:
    return client.get("/api/me", headers=headers).json()["id"]


def test_ping_marks_user_online_with_ip_device_and_page(client, admin, auth, db):
    r = client.post("/api/me/ping", json={"page": "project"}, headers={**auth, "User-Agent": "Mozilla/5.0 (iPhone) Safari/604.1"})
    assert r.status_code == 204
    me = uid(client, auth)
    p = client.get("/api/admin/presence", headers=admin).json()
    row = next(x for x in p["items"] if x["id"] == me)
    assert row["presence"] == "online" and row["last_seen_page"] == "project" and row["last_seen_ip"]
    assert "iPhone" in row["last_seen_ua"] and p["online"] >= 1
    assert client.get("/api/admin/overview", headers=admin).json()["online_now"] >= 1
    users = client.get("/api/admin/users", params={"state": "online"}, headers=admin).json()["items"]
    assert any(u["id"] == me and u["presence"] == "online" for u in users)


def test_presence_goes_recent_then_offline(client, admin, auth, db):
    client.post("/api/me/ping", json={}, headers=auth)
    me = uid(client, auth)
    u = db.get(m.User, __import__("uuid").UUID(me))
    u.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    row = next(x for x in client.get("/api/admin/presence", headers=admin).json()["items"] if x["id"] == me)
    assert row["presence"] == "recent"
    u.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    assert all(x["id"] != me for x in client.get("/api/admin/presence", headers=admin).json()["items"])
    assert all(x["id"] != me for x in client.get("/api/admin/users", params={"state": "online"}, headers=admin).json()["items"])


def test_ping_rejects_odd_page_names_and_needs_login(client, auth):
    assert client.post("/api/me/ping", json={"page": "<script>"}, headers=auth).status_code == 422
    assert client.post("/api/me/ping", json={}).status_code == 401


def test_user_detail_lists_ips_and_old_ip_is_cleared(client, admin, auth, db):
    me = uid(client, auth)
    d = client.get(f"/api/admin/users/{me}", headers=admin).json()
    assert d["ips"] and d["ips"][0]["logins"] >= 1 and d["user"]["presence"] in ("online", "recent")
    u = db.get(m.User, __import__("uuid").UUID(me))
    u.last_seen_at = datetime.now(timezone.utc) - timedelta(days=audit.RETENTION_DAYS + 1)
    db.commit()
    audit.purge_old(db)
    db.commit()
    db.refresh(u)
    assert u.last_seen_ip is None and u.last_seen_at is not None


def test_presence_is_admin_only(client, auth):
    assert client.get("/api/admin/presence", headers=auth).status_code == 404


def test_members_csv_follows_filters_and_is_excel_safe(client, admin, auth, db):
    client.post("/api/me/ping", json={}, headers=auth)
    signup(client, name="=HYPERLINK(\"x\")", email="csv@example.com")
    r = client.get("/api/admin/users.csv", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.text.startswith("\ufeff이름,이메일")
    assert "'=HYPERLINK" in r.text                       # 수식 실행 방지
    online = client.get("/api/admin/users.csv", params={"state": "online"}, headers=admin).text
    assert "접속 중" in online and "csv@example.com" not in online
    assert client.get("/api/admin/users.csv", headers=auth).status_code == 404


# ---------- 동시 접속 막기 ----------
def test_second_login_logs_out_the_first(client):
    signup(client, name="한명", email="one@example.com", password="password123")
    login = lambda: {"Authorization": "Bearer " + client.post(  # noqa: E731
        "/api/auth/login", json={"email": "one@example.com", "password": "password123"}).json()["access_token"]}
    pc1 = login()
    assert client.get("/api/me", headers=pc1).status_code == 200
    pc2 = login()                                                     # 다른 PC 에서 로그인
    r = client.get("/api/me", headers=pc1)
    assert r.status_code == 401 and r.headers["X-Session-Replaced"] == "1"
    assert r.json()["detail"] == "다른 PC에서 접속 중입니다. 자동으로 로그아웃 됩니다."
    assert client.get("/api/me", headers=pc2).status_code == 200      # 마지막 로그인만 통과
    assert client.post("/api/me/ping", json={}, headers=pc1).status_code == 401


def test_tokens_from_before_the_feature_still_work_until_next_login(client, db):
    from education.security import create_token
    h = signup(client, name="예전", email="old@example.com", password="password123")
    uid = client.get("/api/me", headers=h).json()["id"]
    user = db.get(m.User, __import__("uuid").UUID(uid))
    user.session_id = None
    db.commit()
    old = {"Authorization": "Bearer " + create_token(user.id)}       # sid 없는 예전 토큰
    assert client.get("/api/me", headers=old).status_code == 200
    client.post("/api/auth/login", json={"email": "old@example.com", "password": "password123"})
    assert client.get("/api/me", headers=old).status_code == 401

