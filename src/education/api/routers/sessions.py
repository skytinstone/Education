from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import (FILE_ONLY_TEXT, ChatFileOut, DriveConfig, MessageEdit, MessageIn, MessageOut, SessionDetail,
                               SessionIn, SessionOut, SessionPatch, StopIn)
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


STOPPED_TEXT = "답변을 중단했어요."
STOP_TTL = timedelta(days=1)


def _stopped(db: Session, ref: UUID | None) -> bool:
    return ref is not None and db.scalar(select(exists().where(m.ChatStop.ref == ref)))


def _converse(db: Session, user: m.User, s: m.ChatSession, text: str, files: list[m.ChatFile],
              ref: UUID | None = None) -> list[m.Message]:
    """학생 메시지(와 첨부)를 남기고 답변을 만든다. 도중에 '멈추기'(ref)가 오면 질문만 남기고 '중단했어요' 로 답한다."""
    project = db.get(m.Project, s.project_id) if s.project_id else None
    try:
        r = tutor.reply_full(db, user, text, project, files=chat_files.attachments(files) if files else None, session=s,
                             should_stop=lambda: _stopped(db, ref))
        if _stopped(db, ref):  # 답을 다 만든 뒤에 멈췄어도 학생이 멈춘 쪽을 따른다
            raise tutor.Stopped
    except tutor.Stopped:
        r = tutor.Reply(STOPPED_TEXT, intent="stopped")
    msgs = [m.Message(session_id=s.id, role="user", text=text),
            m.Message(session_id=s.id, role="ai", text=r.text, problem_ids=r.problem_ids, explanation=r.explanation,
                      intent=r.intent, suggestions=r.suggestions)]
    db.add_all(msgs)
    db.flush()
    db.expire(s, ["messages"])  # 판단할 때 읽어 둔 대화 목록을 새로 읽게
    for f in files:
        f.message_id = msgs[0].id
    s.updated_at = func.now()
    db.commit()
    return msgs


def _message_out(db: Session, user: m.User, msg: m.Message) -> MessageOut:
    return MessageOut(id=msg.id, role=msg.role, text=msg.text, created_at=msg.created_at, explanation=msg.explanation,
                      intent=msg.intent, suggestions=msg.suggestions or [],
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
    _converse(db, user, s, body.text, files, body.ref)
    return session_detail(db, user, s)


@router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
def stop_reply(body: StopIn, user: CurrentUser, db: DB) -> Response:
    """'답변 멈추기' — 그 답을 만드는 요청이 다음 단계 전에 보고 멈춘다. 이미 끝났으면 아무 일도 없다."""
    db.execute(delete(m.ChatStop).where(m.ChatStop.created_at < datetime.now(UTC) - STOP_TTL))
    db.execute(insert(m.ChatStop).values(ref=body.ref, user_id=user.id).on_conflict_do_nothing())
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}")
def get_session(session_id: UUID, user: CurrentUser, db: DB) -> SessionDetail:
    return session_detail(db, user, owned(db, m.ChatSession, session_id, user))


@router.post("/{session_id}/messages", status_code=status.HTTP_201_CREATED)
def send_message(session_id: UUID, body: MessageIn, user: CurrentUser, db: DB) -> list[MessageOut]:
    s = owned(db, m.ChatSession, session_id, user)
    files = _claim(db, user, body.attachment_ids)
    return [_message_out(db, user, msg) for msg in _converse(db, user, s, body.text, files, body.ref)]


@router.post("/{session_id}/messages/{message_id}/edit")
def edit_message(session_id: UUID, message_id: UUID, body: MessageEdit, user: CurrentUser, db: DB) -> SessionDetail:
    """보낸 질문 고치기 — 그 질문과 뒤의 대화를 지우고, 고친 글로 다시 묻는다. 그 질문의 첨부는 그대로 다시 쓴다."""
    s = owned(db, m.ChatSession, session_id, user)
    target = db.get(m.Message, message_id)
    if target is None or target.session_id != s.id or target.role != "user":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "고칠 질문을 찾을 수 없어요")
    later = list(db.scalars(select(m.Message).where(m.Message.session_id == s.id, m.Message.created_at >= target.created_at)))
    keep = list(target.attachments)
    for f in keep:  # 고친 질문의 첨부는 지우지 않고 새 질문에 다시 붙인다
        f.message_id = None
    db.flush()
    dropped = list(db.scalars(select(m.ChatFile).where(m.ChatFile.message_id.in_([x.id for x in later])))) if later else []
    for x in later:
        db.delete(x)
    db.flush()
    db.expire(s, ["messages"])
    _converse(db, user, s, body.text, keep, body.ref)
    chat_files.remove_disk(dropped)
    return session_detail(db, user, s)


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
