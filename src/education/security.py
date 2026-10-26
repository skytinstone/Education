"""비밀번호 해시(Argon2)와 서명 토큰(JWT).

토큰에는 용도(kind)를 넣어, 로그인 토큰과 간편 로그인용 일회성 티켓이 서로 대신 쓰이지 못하게 한다.
- access : API 호출용 로그인 토큰 (기본 7일)
- login  : 간편 로그인 후 화면이 로그인 토큰으로 바꾸는 짧은 티켓 (2분)
- signup : 처음 온 간편 로그인 사용자가 약관에 동의할 때까지 프로필을 들고 있는 티켓 (15분)
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from education.config import get_settings

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_ticket(kind: str, claims: dict, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {**claims, "kind": kind, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def read_ticket(token: str, kind: str) -> dict | None:
    """서명·만료·용도가 모두 맞으면 내용, 아니면 None."""
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("kind") == kind else None


def create_token(user_id: UUID) -> str:
    return create_ticket("access", {"sub": str(user_id)}, timedelta(days=get_settings().jwt_expire_days))


def read_token(token: str) -> UUID | None:
    """유효한 로그인 토큰이면 사용자 id, 아니면 None (만료·위조·용도 불일치·형식 오류 모두)."""
    payload = read_ticket(token, "access")
    try:
        return UUID(payload["sub"]) if payload else None
    except (KeyError, ValueError):
        return None
