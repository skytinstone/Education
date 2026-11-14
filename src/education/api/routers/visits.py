"""오늘 방문자 수 — 로그인 화면 우측 상단의 '오늘 방문자 N명'.

화면(landing·login·index)이 열릴 때 브라우저의 익명 id 로 POST /api/visits 를 한 번 보내고,
로그인 화면은 GET /api/visits/today 로 숫자를 20초마다 새로 받는다. 로그인 없이 쓸 수 있다.
- 같은 브라우저는 하루에 한 번만 센다 (day, visitor_id 유일)
- 부풀리기 방지: 한 IP 에서 하루에 새로 셀 수 있는 방문자는 IP_DAILY_LIMIT 까지 (IP 는 해시로만 저장)
- '오늘'은 서비스 시간대(TIMEZONE, 기본 Asia/Seoul) 기준, 기록은 90일 뒤 지운다 (services/audit.py)
"""

import hashlib
import hmac
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.api.deps import DB
from education.config import get_settings
from education.db import models as m
from education.services import audit, learning

router = APIRouter(tags=["방문자"])

IP_DAILY_LIMIT = 30  # 학교·학원처럼 한 IP 를 여럿이 쓰는 곳도 고려한 넉넉한 상한
BOT_HINTS = ("bot", "crawl", "spider", "slurp", "preview", "headless", "facebookexternalhit")


class VisitIn(BaseModel):
    visitor_id: UUID
    path: str | None = Field(default=None, max_length=100)


def _ip_hash(request: Request, day: date) -> str | None:
    ip = audit.client_ip(request)
    if not ip:
        return None
    # 날마다 바뀌는 해시 — 같은 날 안에서만 같은 IP 인지 알 수 있고, 원래 IP 는 되돌릴 수 없다
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{day.isoformat()}|{ip}".encode(), hashlib.sha256).hexdigest()


def today_count(db: Session, day: date) -> int:
    return db.scalar(select(func.count()).select_from(m.SiteVisit).where(m.SiteVisit.day == day)) or 0


@router.post("/visits")
def record_visit(body: VisitIn, request: Request, response: Response, db: DB) -> dict:
    """방문 한 번 기록 (같은 브라우저는 하루 한 번만 센다). 오늘 방문자 수를 돌려준다."""
    response.headers["Cache-Control"] = "no-store"
    day = learning.local_today(db)
    ua = (request.headers.get("user-agent") or "").lower()
    if ua and not any(h in ua for h in BOT_HINTS):
        ip_hash = _ip_hash(request, day)
        crowded = ip_hash and (db.scalar(select(func.count()).select_from(m.SiteVisit).where(
            m.SiteVisit.day == day, m.SiteVisit.ip_hash == ip_hash)) or 0) >= IP_DAILY_LIMIT
        if not crowded:
            db.execute(insert(m.SiteVisit).values(day=day, visitor_id=str(body.visitor_id), ip_hash=ip_hash,
                                                  path=(body.path or "")[:100] or None)
                       .on_conflict_do_nothing(constraint="uq_site_visit_day_visitor"))
            db.commit()
    return {"today": today_count(db, day), "date": day.isoformat()}


@router.get("/visits/today")
def visits_today(response: Response, db: DB) -> dict:
    response.headers["Cache-Control"] = "no-store"
    day = learning.local_today(db)
    return {"today": today_count(db, day), "date": day.isoformat()}
