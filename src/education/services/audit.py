"""로그인·가입 기록과 계정 정지.

- 로그인 기록은 성공과 실패를 모두 남긴다 (운영 콘솔 '로그인 기록'에서 확인)
- 개인정보처리방침의 '로그 데이터 최대 90일 보관'에 맞춰, 90일이 지난 기록은 지운다
  (매일 알림 작업 python -m education.reminders 에서, 그리고 운영 콘솔이 기록을 열 때)
"""

from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from education.db import models as m

RETENTION_DAYS = 90


def client_ip(request: Request | None) -> str | None:
    # 운영에서는 uvicorn --proxy-headers 가 Caddy 가 넘겨준 실제 접속 IP 를 request.client 에 넣는다
    return request.client.host[:64] if request and request.client else None


def record_login(db: Session, request: Request | None, *, method: str, ok: bool, user: m.User | None = None,
                 email: str | None = None, kind: str = "login", reason: str | None = None) -> None:
    """로그인·가입 시도 한 번을 기록한다. 커밋은 호출한 쪽이 한다."""
    ua = request.headers.get("user-agent") if request else None
    db.add(m.LoginEvent(
        user_id=user.id if user else None, email=(user.email if user else (email or "").lower() or None),
        method=method, kind=kind, ok=ok, reason=reason, ip=client_ip(request), user_agent=(ua or "")[:300] or None,
    ))
    if ok and user is not None:
        user.last_login_at = datetime.now(timezone.utc)


def purge_old(db: Session) -> int:
    """보관 기간이 지난 로그인 기록을 지운다. 지운 개수를 돌려준다."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    n = db.execute(delete(m.LoginEvent).where(m.LoginEvent.created_at < cutoff)).rowcount or 0
    # 방문자 수 기록도 같은 기간만 남긴다
    db.execute(delete(m.SiteVisit).where(m.SiteVisit.created_at < cutoff))
    return n


def is_suspended(user: m.User | None) -> bool:
    return bool(user and user.suspended_at)
