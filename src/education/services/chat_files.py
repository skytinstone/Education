"""대화 입력창 + 로 첨부하는 사진·PDF.

사진(카메라·앨범), 기기의 파일, Google Drive 에서 고른 파일 모두 화면에서 파일로 받아 같은 길로 올린다
(Drive 파일은 브라우저가 사용자의 Google 권한으로 내려받아 그대로 올림 — 서버는 Google 토큰을 받지 않는다).
형식·크기·쪽수 검사는 기출 업로드(services/materials.py)와 같다.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from education.db import models as m
from education.services.llm import Attachment
from education.services.materials import ALLOWED_TYPES, MAX_BYTES, UPLOAD_DIR, validate_upload

MAX_PER_MESSAGE = 5
CHAT_DIR = "chat"  # UPLOAD_DIR/{user_id}/chat/ — 탈퇴하면 materials.delete_user_files 가 폴더째 지운다


def save(user: m.User, filename: str, content_type: str, data: bytes) -> m.ChatFile:
    file_id = uuid.uuid4()
    folder = UPLOAD_DIR / str(user.id) / CHAT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{file_id}{ALLOWED_TYPES[content_type]}"
    path.write_bytes(data)
    return m.ChatFile(id=file_id, user_id=user.id, filename=Path(filename).name[:255] or "file",
                      content_type=content_type, size_bytes=len(data), storage_path=str(path.relative_to(UPLOAD_DIR)))


def path_of(f: m.ChatFile) -> Path:
    return UPLOAD_DIR / f.storage_path


def claim(db: Session, user: m.User, ids: list[uuid.UUID]) -> list[m.ChatFile]:
    """메시지에 붙일 파일 — 본인이 올렸고 아직 어느 메시지에도 묶이지 않은 것만. 없거나 남의 것이면 ValueError."""
    if not ids:
        return []
    if len(ids) > MAX_PER_MESSAGE:
        raise ValueError(f"한 번에 {MAX_PER_MESSAGE}개까지 첨부할 수 있어요")
    rows = list(db.scalars(select(m.ChatFile).where(
        m.ChatFile.id.in_(ids), m.ChatFile.user_id == user.id, m.ChatFile.message_id.is_(None))))
    if len(rows) != len(set(ids)):
        raise ValueError("첨부 파일을 찾을 수 없어요. 다시 올려 주세요")
    order = {fid: i for i, fid in enumerate(ids)}
    return sorted(rows, key=lambda f: order[f.id])


def attachments(files: list[m.ChatFile]) -> list[Attachment]:
    return [Attachment(data=path_of(f).read_bytes(), mime=f.content_type, filename=f.filename) for f in files]


def remove_disk(files: list[m.ChatFile]) -> None:
    for f in files:
        path_of(f).unlink(missing_ok=True)


__all__ = ["MAX_BYTES", "MAX_PER_MESSAGE", "attachments", "claim", "path_of", "remove_disk", "save", "validate_upload"]
