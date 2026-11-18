from datetime import datetime, timedelta, timezone
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.db.session import get_db
from education.security import read_access

# 같은 계정으로 다른 곳에서 로그인하면, 먼저 로그인한 쪽은 다음 요청에서 이 문구로 로그아웃된다 (화면이 팝업으로 보여 줌)
REPLACED = "다른 PC에서 접속 중입니다. 자동으로 로그아웃 됩니다."

DB = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)


SEEN_EVERY = timedelta(seconds=60)


def touch_seen(db: Session, user: m.User, request: Request | None, page: str | None = None, force: bool = False) -> None:
    """마지막 활동 시각·IP·기기를 남긴다. 요청마다 쓰지 않도록 1분에 한 번 (IP·화면이 바뀌면 바로)."""
    from education.services.audit import client_ip  # 순환 import 방지

    now = datetime.now(timezone.utc)
    ip = client_ip(request)
    stale = user.last_seen_at is None or now - user.last_seen_at >= SEEN_EVERY
    if not (force or stale or (ip and ip != user.last_seen_ip) or (page and page != user.last_seen_page)):
        return
    user.last_seen_at, user.last_seen_ip = now, ip or user.last_seen_ip
    ua = request.headers.get("user-agent") if request else None
    if ua:
        user.last_seen_ua = ua[:300]
    if page:
        user.last_seen_page = page[:24]
    db.commit()


def current_user(request: Request, db: DB, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> m.User:
    got = read_access(cred.credentials) if cred else None
    user = db.get(m.User, got[0]) if got else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요해요", headers={"WWW-Authenticate": "Bearer"})
    # 동시 접속 막기: 마지막으로 로그인한 곳의 토큰만 통과 (이 기능 전에 받은 토큰은 새로 로그인하기 전까지 그대로 둠)
    if user.session_id and got[1] != user.session_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, REPLACED,
                            headers={"WWW-Authenticate": "Bearer", "X-Session-Replaced": "1"})
    if user.suspended_at:  # 정지되면 이미 받은 토큰도 바로 막힌다 (화면은 401 을 받으면 로그아웃)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이용이 정지된 계정이에요", headers={"WWW-Authenticate": "Bearer"})
    touch_seen(db, user, request)
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
