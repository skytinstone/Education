"""AI 사용 한도 세 겹 — 계정당 하루 · 계정당 한 달 · 서비스 전체 하루 (services/quota.py · GET /api/usage)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from conftest import signup
from education.config import get_settings
from education.db import models as m
from education.services import quota


def spend(db, user_id, usd, *, days_ago=0, n=1):
    at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for _ in range(n):
        db.add(m.LLMCall(purpose="generate", model="gpt-x", ok=True, user_id=user_id, cost_usd=usd / n, created_at=at))
    db.flush()


@pytest.fixture
def me(client, auth, db):
    uid = client.get("/api/me", headers=auth).json()["id"]
    return db.get(m.User, uid)


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    s = get_settings()
    for k, v in {"ai_daily_limit_usd": 0.5, "ai_daily_limit_calls": 150, "ai_monthly_limit_usd": 1.5,
                 "ai_global_daily_limit_usd": 20.0}.items():
        monkeypatch.setattr(s, k, v)
    quota._alerted.clear()


def test_usage_summary_shows_percent_not_money(client, auth, db, me):
    spend(db, me.id, 0.25)
    u = client.get("/api/usage", headers=auth).json()
    assert u["today_pct"] == 50 and u["month_pct"] == 17 and u["blocked"] is None and u["plan"] == "free"
    assert "usd" not in str(u).lower()


def test_daily_then_monthly_limit_with_reset_time(db, me, monkeypatch):
    spend(db, me.id, 0.5)
    assert quota.reason(db, me) == quota.MESSAGE and "밤 12시" in quota.MESSAGE
    # 오늘 몫은 남았지만 이번 달 몫을 다 쓴 경우 (어제까지 쓴 것)
    monkeypatch.setattr(get_settings(), "ai_daily_limit_usd", 5.0)
    today = datetime.now(timezone.utc)
    if today.day > 2:  # 같은 달 안에서만 확인할 수 있다
        spend(db, me.id, 1.2, days_ago=1)
        assert quota.reason(db, me) == quota.MONTHLY_MESSAGE and "다음 달 1일" in quota.MONTHLY_MESSAGE


def test_global_daily_cap_stops_everyone_but_admins_and_alerts_once(client, db, me, monkeypatch):
    sent = []
    monkeypatch.setattr(quota.mailer, "send_later", lambda to, subject, body: sent.append((to, subject)))
    monkeypatch.setattr(get_settings(), "admin_emails", "boss@example.com")
    other = signup(client)
    other_id = client.get("/api/me", headers=other).json()["id"]
    spend(db, other_id, 20.0, n=200)  # 다른 사람이 많이 써서 서비스 전체 한도에 닿음
    assert quota.reason(db, me) == quota.GLOBAL_MESSAGE
    assert quota.reason(db, me) == quota.GLOBAL_MESSAGE
    assert len(sent) == 1 and sent[0][0] == "boss@example.com" and "서비스 전체 한도" in sent[0][1]
    boss = signup(client, email="boss@example.com")
    boss_user = db.scalar(select(m.User).where(m.User.email == "boss@example.com"))
    assert boss and quota.reason(db, boss_user) is None  # 운영자는 막지 않는다
    r = client.post("/api/concepts/math.calculus.int_methods.substitution_parts/chat", json={"message": "?"}, headers=other)
    assert r.status_code in (429, 503)  # AI 가 없으면 503, 있으면 한도로 429


def test_zero_means_no_limit(db, me, monkeypatch):
    s = get_settings()
    for k in ("ai_daily_limit_usd", "ai_daily_limit_calls", "ai_monthly_limit_usd", "ai_global_daily_limit_usd"):
        monkeypatch.setattr(s, k, 0)
    spend(db, me.id, 50.0)
    assert quota.reason(db, me) is None
    assert quota.summary(db, me)["unlimited"] is True
