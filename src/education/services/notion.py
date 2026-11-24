"""Notion 연결 — 시험 기록·AI 면접 리포트·오답노트를 사용자의 Notion 에 저장한다.

- Notion 공개 통합(OAuth). 운영자가 NOTION_CLIENT_ID · NOTION_CLIENT_SECRET 을 넣어야 켜진다
  (리디렉션 URI: {PUBLIC_BASE_URL}/api/notion/callback).
- 처음 저장할 때 Notion 에 'Eureka 학습 기록' 페이지와 그 아래 '시험 기록' · 'AI 면접' 데이터베이스를 만든다.
- 내용은 화면이 만든 Markdown 을 받아 Notion 블록(제목·표·목록·체크박스·인용·수식)으로 바꾼다.
- 접근 토큰은 암호화해 저장하고, 같은 결과(ref)는 한 번만 저장한다.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx2
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
MAX_TEXT = 1900          # rich_text 한 조각 최대 2000자
MAX_CHILDREN = 100       # 한 번에 붙일 수 있는 블록 수


class NotionError(Exception):
    """Notion API 오류 — 화면에 보여 줄 한국어 문장을 담는다."""


# ---------------------------------------------------------------- 설정 · 암호화

def available() -> bool:
    s = get_settings()
    return bool(s.notion_client_id and s.notion_client_secret)


def redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/notion/callback"


def authorize_url(state: str) -> str:
    q = {"client_id": get_settings().notion_client_id, "response_type": "code", "owner": "user",
         "redirect_uri": redirect_uri(), "state": state}
    return f"https://api.notion.com/v1/oauth/authorize?{urlencode(q)}"


def _fernet() -> Fernet:
    key = hashlib.sha256(f"notion-token:{get_settings().jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def unseal(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as e:  # 서버 비밀값이 바뀌었으면 다시 연결해야 한다
        raise NotionError("Notion 연결이 만료됐어요. 설정에서 다시 연결해 주세요") from e


# ---------------------------------------------------------------- HTTP

def _http(method: str, url: str, *, token: str | None = None, json: dict | None = None, basic: tuple[str, str] | None = None) -> dict:
    headers = {"Notion-Version": VERSION, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx2.Client(timeout=20) as http:
            r = http.request(method, url, headers=headers, json=json, auth=basic)
    except httpx2.HTTPError as e:
        raise NotionError("Notion 에 연결하지 못했어요. 잠시 후 다시 시도해 주세요") from e
    if r.status_code == 401:
        raise NotionError("Notion 연결이 끊겼어요. 설정에서 다시 연결해 주세요")
    if r.status_code == 429:
        raise NotionError("Notion 이 잠시 바빠요. 조금 뒤에 다시 시도해 주세요")
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = r.text[:200]
        raise NotionError(f"Notion 에 저장하지 못했어요 ({r.status_code}: {msg[:120]})")
    return r.json()


def exchange_code(code: str) -> dict:
    s = get_settings()
    return _http("POST", f"{API}/oauth/token", basic=(s.notion_client_id, s.notion_client_secret),
                 json={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})


# ---------------------------------------------------------------- Markdown → Notion 블록

_INLINE = re.compile(r"(\*\*[^*]+\*\*|\$[^$\n]+\$|`[^`\n]+`|_[^_\n]+_)")


def rich(text: str) -> list[dict]:
    """한 줄 글 → rich_text. **굵게** · _기울임_ · `코드` · $수식$ (Notion 인라인 수식)."""
    out: list[dict] = []
    for part in _INLINE.split(text or ""):
        if not part:
            continue
        if part.startswith("$") and part.endswith("$") and len(part) > 2:
            out.append({"type": "equation", "equation": {"expression": part[1:-1][:MAX_TEXT]}})
            continue
        ann = {}
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            part, ann = part[2:-2], {"bold": True}
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            part, ann = part[1:-1], {"code": True}
        elif part.startswith("_") and part.endswith("_") and len(part) > 2:
            part, ann = part[1:-1], {"italic": True}
        for i in range(0, len(part), MAX_TEXT):
            out.append({"type": "text", "text": {"content": part[i:i + MAX_TEXT]}, **({"annotations": ann} if ann else {})})
    return out or [{"type": "text", "text": {"content": ""}}]


def _block(kind: str, text: str, **extra) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rich(text), **extra}}


def _cells(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def md_to_blocks(md: str) -> list[dict]:
    blocks: list[dict] = []
    lines = (md or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("|"):  # 표: 첫 줄은 머리, 둘째 줄(---)은 건너뛴다
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = _cells(lines[i])
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            width = max(len(r) for r in rows)
            blocks.append({"object": "block", "type": "table", "table": {
                "table_width": width, "has_column_header": True, "has_row_header": False,
                "children": [{"object": "block", "type": "table_row",
                              "table_row": {"cells": [rich(c) for c in (r + [""] * (width - len(r)))]}} for r in rows[:99]]}})
            continue
        if line.startswith("### "):
            blocks.append(_block("heading_3", line[4:]))
        elif line.startswith("## "):
            blocks.append(_block("heading_2", line[3:]))
        elif line.startswith("# "):
            blocks.append(_block("heading_1", line[2:]))
        elif line.startswith("> "):
            blocks.append(_block("quote", line[2:]))
        elif re.match(r"^- \[[ xX]\] ", line):
            blocks.append(_block("to_do", line[6:], checked=line[3] in "xX"))
        elif line.startswith("- "):
            blocks.append(_block("bulleted_list_item", line[2:]))
        elif re.match(r"^\d+\. ", line):
            blocks.append(_block("numbered_list_item", re.sub(r"^\d+\. ", "", line)))
        elif line.strip() == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append(_block("paragraph", line))
        i += 1
    return blocks


# ---------------------------------------------------------------- 저장 공간 · 저장

EXAM_DB = {"이름": {"title": {}}, "날짜": {"date": {}}, "점수": {"number": {}}, "맞힌 문항": {"rich_text": {}}}
INTERVIEW_DB = {"이름": {"title": {}}, "날짜": {"date": {}}, "종류": {"select": {}}, "등급": {"rich_text": {}}, "점수": {"number": {}}}


def _title(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": (text or "Eureka")[:200]}}]


def ensure_space(db: Session, link: m.NotionLink, token: str) -> None:
    """처음 저장할 때 'Eureka 학습 기록' 페이지와 데이터베이스 두 개를 만든다."""
    if link.root_page_id and link.exam_db_id and link.interview_db_id:
        return
    if not link.root_page_id:
        page = {"icon": {"type": "emoji", "emoji": "📚"},
                "properties": {"title": {"title": _title("Eureka 학습 기록")}},
                "children": [_block("paragraph", "Eureka 에서 본 시험 결과와 AI 면접 리포트가 여기에 저절로 쌓여요.")]}
        try:  # 공개 통합은 워크스페이스 맨 위에 페이지를 만들 수 있다
            root = _http("POST", f"{API}/pages", token=token, json={"parent": {"type": "workspace", "workspace": True}, **page})
        except NotionError:  # 안 되면 연결할 때 허용한 페이지 아래에
            found = _http("POST", f"{API}/search", token=token,
                          json={"filter": {"property": "object", "value": "page"}, "page_size": 1})
            if not found.get("results"):
                raise NotionError("Notion 에서 Eureka 가 쓸 수 있는 페이지가 없어요. 다시 연결하면서 페이지를 하나 골라 주세요")
            root = _http("POST", f"{API}/pages", token=token, json={"parent": {"page_id": found["results"][0]["id"]}, **page})
        link.root_page_id = root["id"]
    for attr, name, emoji, props in (("exam_db_id", "시험 기록", "📝", EXAM_DB), ("interview_db_id", "AI 면접", "🎙️", INTERVIEW_DB)):
        if not getattr(link, attr):
            d = _http("POST", f"{API}/databases", token=token, json={
                "parent": {"type": "page_id", "page_id": link.root_page_id}, "icon": {"type": "emoji", "emoji": emoji},
                "title": _title(name), "properties": props})
            setattr(link, attr, d["id"])
    db.flush()


def _props(kind: str, title: str, props: dict) -> dict:
    when = props.get("date") or datetime.now(timezone.utc).isoformat()
    out = {"이름": {"title": _title(title)}, "날짜": {"date": {"start": str(when)[:32]}}}
    if isinstance(props.get("score"), (int, float)):
        out["점수"] = {"number": props["score"]}
    if kind == "exam" and props.get("correct"):
        out["맞힌 문항"] = {"rich_text": rich(str(props["correct"])[:50])}
    if kind == "interview":
        if props.get("kind_name"):
            out["종류"] = {"select": {"name": str(props["kind_name"])[:90].replace(",", " ")}}
        if props.get("level"):
            out["등급"] = {"rich_text": rich(str(props["level"])[:50])}
    return out


def save(db: Session, link: m.NotionLink, *, kind: str, ref: str | None, title: str, markdown: str, props: dict) -> tuple[str, bool]:
    """(Notion 페이지 주소, 새로 만들었는지). 같은 ref 는 한 번만 저장한다."""
    synced = dict(link.synced or {})
    if ref and ref in synced:
        return synced[ref], False
    token = unseal(link.token_sealed)
    ensure_space(db, link, token)
    blocks = md_to_blocks(markdown)
    # 첫 줄 제목은 페이지 제목과 겹치니 뺀다
    if blocks and blocks[0]["type"] == "heading_1":
        blocks = blocks[1:]
    if kind == "exam":
        parent, properties = {"database_id": link.exam_db_id}, _props(kind, title, props)
    elif kind == "interview":
        parent, properties = {"database_id": link.interview_db_id}, _props(kind, title, props)
    else:
        parent, properties = {"page_id": link.root_page_id}, {"title": {"title": _title(title)}}
    page = _http("POST", f"{API}/pages", token=token, json={
        "parent": parent, "properties": properties, "children": blocks[:MAX_CHILDREN]})
    for i in range(MAX_CHILDREN, len(blocks), MAX_CHILDREN):
        _http("PATCH", f"{API}/blocks/{page['id']}/children", token=token, json={"children": blocks[i:i + MAX_CHILDREN]})
    url = page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}"
    if ref:
        synced[ref] = url
        if len(synced) > 2000:  # 오래된 것부터 버린다
            synced = dict(list(synced.items())[-2000:])
        link.synced = synced
    db.flush()
    return url, True
