"""Notion 연결 — Markdown → 블록, 연결(state 서명) · 토큰 암호화, 저장 공간 만들기 · 한 번만 저장 (Notion API 는 가짜)."""

from datetime import timedelta

import pytest

from education.config import get_settings
from education.db import models as m
from education.security import create_ticket
from education.services import notion

MD = """# 미적분 시험 결과

> Eureka 시험 기록 · 2026년 11월 24일

| 점수 | 맞힌 문항 |
| --- | --- |
| 82 / 100점 | 8 / 10 |

## 문항별 결과

- [ ] **3번** $\\int_0^1 x\\,dx$ 의 값은? — 내 답 ② · 정답 ①
- [x] 다시 풀어서 맞히기
1. 첫째 보기
보통 문장 _기울임_ 과 `코드`
"""


@pytest.fixture
def on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "notion_client_id", "cid-123")
    monkeypatch.setattr(s, "notion_client_secret", "csecret")


class FakeNotion:
    """POST /pages · /databases · /search · PATCH children 을 흉내 낸다."""
    def __init__(self, workspace_ok=True):
        self.calls, self.n, self.workspace_ok = [], 0, workspace_ok

    def __call__(self, method, url, *, token=None, json=None, basic=None):
        self.calls.append((method, url.rsplit("/v1", 1)[-1], json))
        self.n += 1
        if url.endswith("/pages") and json["parent"].get("workspace") and not self.workspace_ok:
            raise notion.NotionError("workspace 불가")
        if url.endswith("/search"):
            return {"results": [{"id": "allowed-page"}]}
        return {"id": f"id-{self.n}", "url": f"https://www.notion.so/p{self.n}"}


def test_markdown_to_blocks():
    b = notion.md_to_blocks(MD)
    kinds = [x["type"] for x in b]
    assert kinds[:4] == ["heading_1", "quote", "table", "heading_2"]
    table = b[2]["table"]
    assert table["table_width"] == 2 and len(table["children"]) == 2  # --- 줄은 빠진다
    assert table["children"][1]["table_row"]["cells"][0][0]["text"]["content"] == "82 / 100점"
    todo = b[4]["to_do"]
    assert todo["checked"] is False and any(r["type"] == "equation" for r in todo["rich_text"])
    assert todo["rich_text"][0]["annotations"] == {"bold": True}
    assert b[5]["to_do"]["checked"] is True and kinds[6] == "numbered_list_item"
    para = b[7]["paragraph"]["rich_text"]
    assert {"italic": True} in [r.get("annotations") for r in para] and {"code": True} in [r.get("annotations") for r in para]
    long = notion.rich("가" * 5000)
    assert len(long) == 3 and all(len(r["text"]["content"]) <= 2000 for r in long)


def test_status_and_start(client, auth, on, monkeypatch):
    assert client.get("/api/notion", headers=auth).json() == {"available": True, "connected": False, "workspace": None, "auto": False}
    url = client.post("/api/notion/start", headers=auth).json()["url"]
    assert url.startswith("https://api.notion.com/v1/oauth/authorize?") and "client_id=cid-123" in url and "state=" in url
    monkeypatch.setattr(get_settings(), "notion_client_id", None)
    assert client.post("/api/notion/start", headers=auth).status_code == 503
    assert client.get("/api/notion", headers=auth).json()["available"] is False


def _user_id(client, auth):
    return client.get("/api/me", headers=auth).json()["id"]


def test_callback_links_and_seals_token(client, auth, db, on, monkeypatch):
    monkeypatch.setattr(notion, "exchange_code", lambda code: {"access_token": "secret-token", "workspace_name": "내 공부", "workspace_id": "w1"})
    bad = client.get("/api/notion/callback?code=c&state=forged", follow_redirects=False)
    assert bad.status_code == 302 and "notion_error=state" in bad.headers["location"]
    denied = client.get("/api/notion/callback?error=access_denied", follow_redirects=False)
    assert "notion_error=denied" in denied.headers["location"]
    state = create_ticket("notion_link", {"sub": _user_id(client, auth)}, timedelta(minutes=10))
    r = client.get(f"/api/notion/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("#/settings?notion=connected")
    st = client.get("/api/notion", headers=auth).json()
    assert st["connected"] and st["workspace"] == "내 공부" and st["auto"] is True
    link = db.query(m.NotionLink).one()
    assert "secret-token" not in link.token_sealed and notion.unseal(link.token_sealed) == "secret-token"
    # 다른 사람의 state 로는 남의 계정에 붙지 않는다 (서명이 다르면 거절)
    other = create_ticket("login", {"sub": _user_id(client, auth)}, timedelta(minutes=10))
    assert "notion_error=state" in client.get(f"/api/notion/callback?code=c&state={other}", follow_redirects=False).headers["location"]


def _connect(client, auth, monkeypatch):
    monkeypatch.setattr(notion, "exchange_code", lambda code: {"access_token": "tok", "workspace_name": "WS", "workspace_id": "w1"})
    state = create_ticket("notion_link", {"sub": _user_id(client, auth)}, timedelta(minutes=10))
    client.get(f"/api/notion/callback?code=c&state={state}", follow_redirects=False)


def test_export_creates_space_once_and_dedups(client, auth, on, monkeypatch):
    body = {"kind": "exam", "ref": "exam:1", "title": "미적분 시험", "markdown": MD, "props": {"score": 82, "correct": "8 / 10"}}
    assert client.post("/api/notion/export", json=body, headers=auth).status_code == 409  # 연결 전
    _connect(client, auth, monkeypatch)
    fake = FakeNotion()
    monkeypatch.setattr(notion, "_http", fake)
    r = client.post("/api/notion/export", json=body, headers=auth).json()
    assert r["created"] is True and r["url"].startswith("https://www.notion.so/")
    paths = [c[1] for c in fake.calls]
    assert paths == ["/pages", "/databases", "/databases", "/pages"]  # 학습 기록 페이지 · 시험 기록 · AI 면접 · 결과 페이지
    root, page = fake.calls[0][2], fake.calls[3][2]
    assert root["parent"] == {"type": "workspace", "workspace": True}
    assert page["parent"] == {"database_id": "id-2"} and page["properties"]["점수"] == {"number": 82}
    assert page["children"][0]["type"] == "quote"  # 첫 제목은 페이지 제목과 겹쳐 뺀다
    again = client.post("/api/notion/export", json=body, headers=auth).json()
    assert again == {"url": r["url"], "created": False} and len(fake.calls) == 4  # 같은 결과는 다시 저장하지 않는다
    # 면접은 AI 면접 데이터베이스로, 오답노트는 학습 기록 페이지 아래로 (공간은 다시 만들지 않는다)
    client.post("/api/notion/export", json={**body, "kind": "interview", "ref": "interview:1", "props": {"kind_name": "OPIc 영어", "level": "IH"}}, headers=auth)
    assert fake.calls[-1][2]["parent"] == {"database_id": "id-3"} and fake.calls[-1][2]["properties"]["종류"] == {"select": {"name": "OPIc 영어"}}
    client.post("/api/notion/export", json={**body, "kind": "notes", "ref": None}, headers=auth)
    assert fake.calls[-1][2]["parent"] == {"page_id": "id-1"} and len(fake.calls) == 6


def test_export_falls_back_to_allowed_page_and_long_content(client, auth, on, monkeypatch):
    _connect(client, auth, monkeypatch)
    fake = FakeNotion(workspace_ok=False)
    monkeypatch.setattr(notion, "_http", fake)
    md = "# 제목\n" + "\n".join(f"- 줄 {i}" for i in range(250))
    client.post("/api/notion/export", json={"kind": "notes", "title": "오답노트", "markdown": md}, headers=auth)
    paths = [c[1] for c in fake.calls]
    assert paths[:3] == ["/pages", "/search", "/pages"] and fake.calls[2][2]["parent"] == {"page_id": "allowed-page"}
    appended = [c for c in fake.calls if c[0] == "PATCH"]
    assert len(appended) == 2 and sum(len(c[2]["children"]) for c in appended) == 150  # 100개씩 나눠 붙인다


def test_auto_toggle_and_disconnect(client, auth, on, monkeypatch):
    assert client.patch("/api/notion", json={"auto": False}, headers=auth).status_code == 404
    _connect(client, auth, monkeypatch)
    assert client.patch("/api/notion", json={"auto": False}, headers=auth).json()["auto"] is False
    assert client.delete("/api/notion", headers=auth).status_code == 204
    assert client.get("/api/notion", headers=auth).json()["connected"] is False
