from uuid import UUID

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import MessageIn, MessageOut, SessionDetail, SessionIn, SessionOut, SessionPatch
from education.db import models as m
from education.services import learning, tutor

router = APIRouter(prefix="/sessions", tags=["대화"])


def _converse(db: Session, user: m.User, s: m.ChatSession, text: str) -> list[m.Message]:
    """학생 메시지를 남기고 답변을 만든다."""
    project = db.get(m.Project, s.project_id) if s.project_id else None
    reply_text, problem_ids = tutor.reply(db, user, text, project)
    msgs = [m.Message(session_id=s.id, role="user", text=text),
            m.Message(session_id=s.id, role="ai", text=reply_text, problem_ids=problem_ids)]
    db.add_all(msgs)
    s.updated_at = func.now()
    db.commit()
    return msgs


def _message_out(db: Session, user: m.User, msg: m.Message) -> MessageOut:
    return MessageOut(id=msg.id, role=msg.role, text=msg.text, created_at=msg.created_at,
                      problems=learning.problem_views(db, user, msg.problem_ids, session_id=msg.session_id))


def session_detail(db: Session, user: m.User, s: m.ChatSession) -> SessionDetail:
    db.refresh(s)
    return SessionDetail(**SessionOut.model_validate(s).model_dump(),
                         messages=[_message_out(db, user, msg) for msg in s.messages])


@router.get("")
def list_sessions(user: CurrentUser, db: DB, project_id: UUID | None = None, limit: int = 50) -> list[SessionOut]:
    q = select(m.ChatSession).where(m.ChatSession.user_id == user.id)
    if project_id:
        q = q.where(m.ChatSession.project_id == project_id)
    q = q.order_by(m.ChatSession.updated_at.desc()).limit(min(limit, 200))
    return [SessionOut.model_validate(s) for s in db.scalars(q)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(body: SessionIn, user: CurrentUser, db: DB) -> SessionDetail:
    """새 학습: 첫 메시지로 대화를 만들고 바로 답변까지 붙인다."""
    if body.project_id:
        owned(db, m.Project, body.project_id, user)
    title = body.text.strip()
    s = m.ChatSession(user_id=user.id, project_id=body.project_id, title=title if len(title) <= 24 else f"{title[:24]}…")
    db.add(s)
    db.flush()
    _converse(db, user, s, body.text.strip())
    return session_detail(db, user, s)


@router.get("/{session_id}")
def get_session(session_id: UUID, user: CurrentUser, db: DB) -> SessionDetail:
    return session_detail(db, user, owned(db, m.ChatSession, session_id, user))


@router.post("/{session_id}/messages", status_code=status.HTTP_201_CREATED)
def send_message(session_id: UUID, body: MessageIn, user: CurrentUser, db: DB) -> list[MessageOut]:
    s = owned(db, m.ChatSession, session_id, user)
    return [_message_out(db, user, msg) for msg in _converse(db, user, s, body.text.strip())]


@router.patch("/{session_id}")
def update_session(session_id: UUID, body: SessionPatch, user: CurrentUser, db: DB) -> SessionOut:
    s = owned(db, m.ChatSession, session_id, user)
    if body.title:
        s.title = body.title.strip()
    if "project_id" in body.model_fields_set:  # null 이면 프로젝트에서 뺀다
        if body.project_id:
            owned(db, m.Project, body.project_id, user)
        s.project_id = body.project_id
    db.commit()
    return SessionOut.model_validate(s)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: UUID, user: CurrentUser, db: DB) -> Response:
    db.delete(owned(db, m.ChatSession, session_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
