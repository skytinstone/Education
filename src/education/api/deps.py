from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.db.session import get_db
from education.security import read_token

DB = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)


def current_user(db: DB, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> m.User:
    user_id = read_token(cred.credentials) if cred else None
    user = db.get(m.User, user_id) if user_id else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요해요", headers={"WWW-Authenticate": "Bearer"})
    if user.suspended_at:  # 정지되면 이미 받은 토큰도 바로 막힌다 (화면은 401 을 받으면 로그아웃)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이용이 정지된 계정이에요", headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[m.User, Depends(current_user)]


def is_admin(user: m.User) -> bool:
    return user.email.lower() in get_settings().admins


def admin_user(user: CurrentUser) -> m.User:
    """운영자(.env 의 ADMIN_EMAILS)만. 아니면 운영자 경로가 있다는 것도 알리지 않게 404."""
    if not is_admin(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "찾을 수 없어요")
    return user


AdminUser = Annotated[m.User, Depends(admin_user)]

T = TypeVar("T")


def owned(db: Session, model: type[T], obj_id: UUID, user: m.User) -> T:
    """내 데이터만 꺼낸다. 남의 것이거나 없으면 똑같이 404 (존재 여부를 노출하지 않음)."""
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "찾을 수 없어요")
    return obj
