"""운영 안정화 — 로그인 차단, 비밀번호 재설정, AI 하루 한도, 멈춘 작업 정리, 보안 헤더, 관리자 품질·퍼널."""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from conftest import signup
from education.api.routers import auth as auth_router
from education.api.routers import projects as projects_router
from education.config import get_settings
from education.db import models as m
from education.services import jobs, mailer, tutor


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ---------- 로그인 차단 ----------
def test_repeated_failures_lock_the_email_for_a_while(client):
    signup(client, email="lock@example.com", password="right-pass1")
    for _ in range(5):
        assert login(client, "lock@example.com", "wrong-pass1").status_code == 401
    r = login(client, "lock@example.com", "right-pass1")   # 맞는 비밀번호도 잠시 막힘
    assert r.status_code == 429 and "15분" in r.json()["detail"]
    signup(client, email="other@example.com", password="right-pass1")
    assert login(client, "other@example.com", "right-pass1").status_code == 200  # 다른 계정은 그대로


# ---------- 비밀번호 재설정 ----------
@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_later", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(mailer, "configured", lambda: True)
    auth_router._reset_sent.clear()
    return sent


def test_password_reset_by_mail_link(client, outbox):
    signup(client, email="forgot@example.com", password="old-pass12")
    r = client.post("/api/auth/password/forgot", json={"email": "Forgot@example.com"})
    assert r.status_code == 202 and r.json() == {"mail": True}
    to, subject, body = outbox[0]
    assert to == "forgot@example.com" and "비밀번호" in subject
    token = re.search(r"#reset=(\S+)", body).group(1)

    r = client.post("/api/auth/password/reset", json={"token": token, "password": "new-pass34"})
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.post("/api/auth/password/reset", json={"token": token, "password": "again-pass56"}).status_code == 400  # 한 번만
    assert login(client, "forgot@example.com", "old-pass12").status_code == 401
    assert login(client, "forgot@example.com", "new-pass34").status_code == 200


def test_forgot_does_not_reveal_accounts(client, outbox):
    r = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    assert r.status_code == 202 and outbox == []
    assert client.post("/api/auth/password/reset", json={"token": "garbage", "password": "new-pass34"}).status_code == 400


# ---------- AI 하루 한도 ----------
def add_calls(db, user_id, n):
    for _ in range(n):
        db.add(m.LLMCall(purpose="generate", model="gpt-x", ok=True, user_id=user_id, cost_usd=0.01))
    db.flush()


def test_daily_ai_limit(client, auth, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_daily_limit_calls", 3)
    uid = client.get("/api/me", headers=auth).json()["id"]
    pid = client.post("/api/projects", json={"name": "p", "subject_id": "math.math1"}, headers=auth).json()["id"]
    add_calls(db, uid, 3)
    monkeypatch.setattr(projects_router, "get_llm", lambda: object())
    r = client.post(f"/api/projects/{pid}/generate", json={"level": "same", "count": 1}, headers=auth)
    assert r.status_code == 429 and "AI 사용량" in r.json()["detail"]
    # 대화는 막지 않고 문제 은행으로 답한다
    monkeypatch.setattr(tutor, "get_llm", lambda: object())
    s = client.post("/api/sessions", json={"text": "로그 문제 2문제 내줘"}, headers=auth).json()
    assert "AI 사용량" in s["messages"][1]["text"]


def test_admins_have_no_ai_limit(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", "boss@example.com")
    monkeypatch.setattr(get_settings(), "ai_daily_limit_calls", 1)
    headers = signup(client, email="boss@example.com")
    add_calls(db, client.get("/api/me", headers=headers).json()["id"], 5)
    from education.services import quota
    assert quota.exceeded(db, db.scalar(select(m.User).where(m.User.email == "boss@example.com"))) is False


# ---------- 멈춘 작업 정리 ----------
def test_stale_jobs_are_marked_failed():
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    mat = m.Material(status="extracting", created_at=old, answer_key_status="running", answer_key_started_at=old)
    assert jobs.heal(None, mat) is True
    assert mat.status == "failed" and mat.answer_key_status == "failed" and "다시 시도" in mat.error
    fresh = m.Material(status="extracting", created_at=datetime.now(timezone.utc), answer_key_status=None)
    assert jobs.heal(None, fresh) is False and fresh.status == "extracting"


# ---------- 보안 헤더 · 검색 ----------
def test_security_headers_robots_and_sitemap(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "SAMEORIGIN"
    assert "microphone=(self)" in r.headers["permissions-policy"]
    robots = client.get("/robots.txt").text
    assert "Disallow: /api/" in robots and "Sitemap:" in robots
    assert "<loc>" in client.get("/sitemap.xml").text


# ---------- 관리자: 문제 품질 · 퍼널 ----------
def test_admin_quality_and_funnel(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", "boss@example.com")
    admin = signup(client, email="boss@example.com")
    for ok, reason in ((True, None), (False, "정답 불일치: 출제 3, 검증 4"), (False, "문제 결함: 복수 정답")):
        pid = f"ai_{uuid.uuid4().hex[:12]}"
        db.add(m.Problem(id=pid, domain="math", difficulty=2, problem_type="multiple_choice", stem="x", choices=["1", "2"],
                         answer="1", solution="s", source="generated", verification="verified" if ok else "rejected",
                         generation_meta={"reject_reason": reason}))
    db.flush()
    q = client.get("/api/admin/quality", headers=admin).json()
    assert q["generated"]["total"] >= 3 and q["generated"]["passed"] >= 1
    assert {"정답 불일치", "문제 결함"} <= {r["reason"] for r in q["reasons"]}

    f = client.get("/api/admin/funnel", headers=admin).json()
    assert [s["key"] for s in f["steps"]] == ["visitors", "signups", "activated", "returned"]
    assert f["steps"][1]["count"] >= 1 and f["cohorts"]
