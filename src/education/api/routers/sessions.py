from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import (FILE_ONLY_TEXT, ChatFileOut, DriveConfig, MessageIn, MessageOut, SessionDetail, SessionIn, SessionOut,
                               SessionPatch)
from education.config import get_settings
from education.db import models as m
from education.services import chat_files, learning, tutor

router = APIRouter(prefix="/sessions", tags=["대화"])

UNSENT_TTL = timedelta(days=1)  # 올려 두고 보내지 않은 첨부는 하루 뒤 거둔다


def _claim(db: Session, user: m.User, ids: list[UUID]) -> list[m.ChatFile]:
    try:
        return chat_files.claim(db, user, ids)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e


def _converse(db: Session, user: m.User, s: m.ChatSession, text: str, files: list[m.ChatFile]) -> list[m.Message]:
    """학생 메시지(와 첨부)를 남기고 답변을 만든다."""
    project = db.get(m.Project, s.project_id) if s.project_id else None
    reply_text, problem_ids, explanation = tutor.reply_full(
        db, user, text, project, files=chat_files.attachments(files) if files else None)
    msgs = [m.Message(session_id=s.id, role="user", text=text),
            m.Message(session_id=s.id, role="ai", text=reply_text, problem_ids=problem_ids, explanation=explanation)]
    db.add_all(msgs)
    db.flush()
    for f in files:
        f.message_id = msgs[0].id
    s.updated_at = func.now()
    db.commit()
    return msgs


def _message_out(db: Session, user: m.User, msg: m.Message) -> MessageOut:
    return MessageOut(id=msg.id, role=msg.role, text=msg.text, created_at=msg.created_at, explanation=msg.explanation,
                      attachments=[ChatFileOut.model_validate(f) for f in msg.attachments],
                      problems=learning.problem_views(db, user, msg.problem_ids, session_id=msg.session_id))


# ---------- 첨부 (입력창 +) ----------
@router.post("/files", status_code=status.HTTP_201_CREATED)
def upload_file(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()]) -> ChatFileOut:
    """사진·PDF 를 먼저 올려 id 를 받는다. 메시지를 보낼 때 attachment_ids 로 붙인다."""
    data = file.file.read(chat_files.MAX_BYTES + 1)
    if error := chat_files.validate_upload(file.content_type or "", data):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error)
    stale = list(db.scalars(select(m.ChatFile).where(
        m.ChatFile.user_id == user.id, m.ChatFile.message_id.is_(None),
        m.ChatFile.created_at < datetime.now(UTC) - UNSENT_TTL)))
    for f in stale:
        db.delete(f)
    f = chat_files.save(user, file.filename or "file", file.content_type, data)
    db.add(f)
    db.commit()
    chat_files.remove_disk(stale)
    return ChatFileOut.model_validate(f)


@router.get("/files/{file_id}")
def get_file(file_id: UUID, user: CurrentUser, db: DB) -> FileResponse:
    f = owned(db, m.ChatFile, file_id, user)
    path = chat_files.path_of(f)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "파일을 찾을 수 없어요")
    return FileResponse(path, media_type=f.content_type, filename=f.filename, content_disposition_type="inline",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: UUID, user: CurrentUser, db: DB) -> Response:
    """보내기 전에 첨부를 빼면 지운다 (이미 보낸 메시지의 첨부는 대화를 지울 때 함께 지워진다)."""
    f = owned(db, m.ChatFile, file_id, user)
    if f.message_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 보낸 메시지의 첨부예요")
    db.delete(f)
    db.commit()
    chat_files.remove_disk([f])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/drive-config")
def drive_config(user: CurrentUser) -> DriveConfig | None:
    """Google Drive 에서 고르기에 필요한 공개 값. 설정이 없으면 null (화면에서 메뉴를 숨김)."""
    s = get_settings()
    if not (s.google_client_id and s.google_picker_api_key and s.google_app_id):
        return None
    return DriveConfig(client_id=s.google_client_id, api_key=s.google_picker_api_key, app_id=s.google_app_id)


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
    files = _claim(db, user, body.attachment_ids)
    title = files[0].filename if files and body.text == FILE_ONLY_TEXT else body.text  # 첨부만 보냈으면 파일 이름으로
    s = m.ChatSession(user_id=user.id, project_id=body.project_id, title=title if len(title) <= 24 else f"{title[:24]}…")
    db.add(s)
    db.flush()
    _converse(db, user, s, body.text, files)
    return session_detail(db, user, s)


@router.get("/{session_id}")
def get_session(session_id: UUID, user: CurrentUser, db: DB) -> SessionDetail:
    return session_detail(db, user, owned(db, m.ChatSession, session_id, user))


@router.post("/{session_id}/messages", status_code=status.HTTP_201_CREATED)
def send_message(session_id: UUID, body: MessageIn, user: CurrentUser, db: DB) -> list[MessageOut]:
    s = owned(db, m.ChatSession, session_id, user)
    files = _claim(db, user, body.attachment_ids)
    return [_message_out(db, user, msg) for msg in _converse(db, user, s, body.text, files)]


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
    s = owned(db, m.ChatSession, session_id, user)
    files = list(db.scalars(select(m.ChatFile).join(m.Message).where(m.Message.session_id == s.id)))
    db.delete(s)
    db.commit()
    chat_files.remove_disk(files)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
