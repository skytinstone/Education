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
from education.services import billing, learning

MESSAGE = "오늘 쓸 수 있는 AI 사용량을 모두 썼어요. 내일 다시 이용해 주세요"


def usage_today(db: Session, user: m.User) -> tuple[float, int]:
    day = func.date(func.timezone(get_settings().timezone, m.LLMCall.created_at))
    cost, calls = db.execute(select(func.coalesce(func.sum(m.LLMCall.cost_usd), 0), func.count())
                             .where(m.LLMCall.user_id == user.id, day == learning.local_today(db))).one()
    return float(cost), int(calls)


def limits(db: Session, user: m.User) -> tuple[float, int]:
    """하루 한도 (비용 USD, 호출 수) — 구독 요금제가 있으면 그 한도, 없으면 .env 의 기본값. 0 = 제한 없음"""
    s = get_settings()
    plan = billing.plan_of(db, user)
    if plan.price:
        # 기본 한도가 0(제한 없음)이면 구독자도 제한 없음, 아니면 둘 중 넉넉한 쪽
        return (s.ai_daily_limit_usd and max(plan.daily_usd, s.ai_daily_limit_usd),
                s.ai_daily_limit_calls and max(plan.daily_calls, s.ai_daily_limit_calls))
    return s.ai_daily_limit_usd, s.ai_daily_limit_calls


def exceeded(db: Session, user: m.User) -> bool:
    if user.email.lower() in get_settings().admins:
        return False
    max_usd, max_calls = limits(db, user)
    cost, calls = usage_today(db, user)
    return bool((max_usd and cost >= max_usd) or (max_calls and calls >= max_calls))


def check(db: Session, user: m.User) -> None:
    """한도를 넘었으면 429."""
    if exceeded(db, user):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, MESSAGE)
