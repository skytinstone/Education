"""오늘 방문자 수 — 같은 브라우저는 하루 한 번, 봇 제외, 한 IP 의 부풀리기 제한."""

import uuid

from education.api.routers import visits
from education.db import models as m


def visit(client, vid=None, ua="Mozilla/5.0 (Windows NT 10.0) Chrome/131.0"):
    return client.post("/api/visits", json={"visitor_id": str(vid or uuid.uuid4()), "path": "/app/login.html"},
                       headers={"User-Agent": ua})


def test_same_browser_counts_once_a_day(client):
    start = client.get("/api/visits/today").json()["today"]
    vid = uuid.uuid4()
    assert visit(client, vid).json()["today"] == start + 1
    assert visit(client, vid).json()["today"] == start + 1  # 새로고침해도 그대로
    assert visit(client).json()["today"] == start + 2       # 다른 브라우저
    r = client.get("/api/visits/today")
    assert r.json()["today"] == start + 2 and r.headers["cache-control"] == "no-store"


def test_bots_are_not_counted(client):
    start = client.get("/api/visits/today").json()["today"]
    assert visit(client, ua="LinkedInBot/1.0 (compatible; Mozilla/5.0)").json()["today"] == start
    assert visit(client, ua="").json()["today"] == start


def test_one_ip_cannot_inflate(client, monkeypatch, db):
    monkeypatch.setattr(visits, "IP_DAILY_LIMIT", 2)
    start = client.get("/api/visits/today").json()["today"]
    for _ in range(5):
        visit(client)
    assert client.get("/api/visits/today").json()["today"] == start + 2
    # IP 는 원문이 아니라 해시로만 남는다
    row = db.query(m.SiteVisit).first()
    assert row.ip_hash and len(row.ip_hash) == 64 and "testclient" not in row.ip_hash


def test_bad_visitor_id_rejected(client):
    assert client.post("/api/visits", json={"visitor_id": "not-a-uuid"}).status_code == 422
