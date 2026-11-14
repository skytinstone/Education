"""계정 삭제 — 본인 탈퇴(DELETE /me)와 운영 콘솔의 계정 삭제가 함께 쓴다."""

from sqlalchemy.orm import Session

from education.db import models as m
from education.services import avatars, materials


def delete_account(db: Session, user: m.User) -> None:
    """계정과 학습 기록(DB 의 ON DELETE CASCADE 로 함께 지워짐), 올린 기출 파일, 프로필 사진을 지운다.
    백업에는 최대 90일 남았다가 자동 삭제된다 (개인정보처리방침 4번)."""
    user_id = user.id
    db.delete(user)
    db.commit()
    avatars.delete_photo(user_id)
    materials.delete_user_files(user_id)
