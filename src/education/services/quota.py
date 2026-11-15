"""하루 AI 사용 한도 — 한 사람이 AI 를 끝없이 돌려 비용이 치솟는 일을 막는다.

오늘(서비스 시간대) 그 사용자로 기록된 llm_calls 의 비용 합과 호출 수를 본다. 운영자(ADMIN_EMAILS)는 제외.
한도는 .env 의 AI_DAILY_LIMIT_USD · AI_DAILY_LIMIT_CALLS (0 이면 제한 없음).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.services import learning

MESSAGE = "오늘 쓸 수 있는 AI 사용량을 모두 썼어요. 내일 다시 이용해 주세요"


def usage_today(db: Session, user: m.User) -> tuple[float, int]:
    day = func.date(func.timezone(get_settings().timezone, m.LLMCall.created_at))
    cost, calls = db.execute(select(func.coalesce(func.sum(m.LLMCall.cost_usd), 0), func.count())
                             .where(m.LLMCall.user_id == user.id, day == learning.local_today(db))).one()
    return float(cost), int(calls)


def exceeded(db: Session, user: m.User) -> bool:
    s = get_settings()
    if user.email.lower() in s.admins:
        return False
    cost, calls = usage_today(db, user)
    return bool((s.ai_daily_limit_usd and cost >= s.ai_daily_limit_usd) or (s.ai_daily_limit_calls and calls >= s.ai_daily_limit_calls))


def check(db: Session, user: m.User) -> None:
    """한도를 넘었으면 429."""
    if exceeded(db, user):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, MESSAGE)
