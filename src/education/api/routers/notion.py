"""Notion 연결 — 상태, 연결 시작·콜백, 자동 저장 켜고 끄기, 저장, 연결 해제 (services/notion.py)."""

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from education.api.deps import DB, CurrentUser
from education.db import models as m
from education.security import create_ticket, read_ticket
from education.services import notion

router = APIRouter(prefix="/notion", tags=["Notion"])
DONE = "/app/index.html#/settings"


class NotionPatch(BaseModel):
    auto: bool


class ExportIn(BaseModel):
    kind: str = Field(pattern="^(exam|interview|notes)$")
    ref: str | None = Field(default=None, max_length=120)   # 같은 결과를 두 번 저장하지 않도록 (예: exam:<id>)
    title: str = Field(max_length=200)
    markdown: str = Field(max_length=200_000)
    props: dict = Field(default_factory=dict)


def _link(db, user: m.User) -> m.NotionLink | None:
    return db.scalar(select(m.NotionLink).where(m.NotionLink.user_id == user.id))


def _status(link: m.NotionLink | None) -> dict:
    return {"available": notion.available(), "connected": link is not None,
            "workspace": link.workspace_name if link else None, "auto": link.auto if link else False}


@router.get("")
def status_(user: CurrentUser, db: DB) -> dict:
    return _status(_link(db, user))


@router.post("/start")
def start(user: CurrentUser) -> dict:
    """연결 시작 — 화면은 돌려받은 url 로 이동한다. state 는 누가 시작했는지 담은 서명 (10분)."""
    if not notion.available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Notion 연결은 아직 준비 중이에요")
    state = create_ticket("notion_link", {"sub": str(user.id)}, timedelta(minutes=10))
    return {"url": notion.authorize_url(state)}


@router.get("/callback")
def callback(db: DB, code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    def back(q: str) -> RedirectResponse:
        return RedirectResponse(f"{DONE}?{q}", status_code=status.HTTP_302_FOUND)
    if error:
        return back("notion_error=denied")
    claims = read_ticket(state or "", "notion_link")
    if not (code and claims):
        return back("notion_error=state")
    user = db.get(m.User, UUID(claims["sub"]))
    if user is None:
        return back("notion_error=state")
    try:
        tok = notion.exchange_code(code)
    except notion.NotionError:
        return back("notion_error=token")
    link = _link(db, user)
    if link is None:
        link = m.NotionLink(user_id=user.id, token_sealed="")
        db.add(link)
    elif link.workspace_id and link.workspace_id != tok.get("workspace_id"):  # 다른 워크스페이스로 바꾸면 저장 공간도 새로
        link.root_page_id = link.exam_db_id = link.interview_db_id = None
        link.synced = {}
    link.token_sealed = notion.seal(tok["access_token"])
    link.workspace_name = (tok.get("workspace_name") or "Notion")[:200]
    link.workspace_id = (tok.get("workspace_id") or "")[:64] or None
    db.commit()
    return back("notion=connected")


@router.patch("")
def patch(body: NotionPatch, user: CurrentUser, db: DB) -> dict:
    link = _link(db, user)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notion 이 연결되어 있지 않아요")
    link.auto = body.auto
    db.commit()
    return _status(link)


@router.post("/export")
def export(body: ExportIn, user: CurrentUser, db: DB) -> dict:
    link = _link(db, user)
    if link is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Notion 이 연결되어 있지 않아요. 설정에서 먼저 연결해 주세요")
    try:
        url, created = notion.save(db, link, kind=body.kind, ref=body.ref, title=body.title,
                                   markdown=body.markdown, props=body.props)
    except notion.NotionError as e:
        db.commit()  # 만들어 둔 저장 공간은 남긴다
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    db.commit()
    return {"url": url, "created": created}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(user: CurrentUser, db: DB) -> Response:
    """연결 해제 — 저장해 둔 Notion 페이지는 그대로 남는다 (Notion 쪽 연결은 Notion 설정에서 끊는다)."""
    link = _link(db, user)
    if link is not None:
        db.delete(link)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
