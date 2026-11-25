"""AI 사용 한도 — 한 사람이나 갑자기 몰린 사용으로 비용이 치솟는 일을 막는다.

세 겹으로 본다 (운영자 ADMIN_EMAILS 는 모두 제외).
1. 계정당 하루: 비용(USD)과 호출 수 — AI_DAILY_LIMIT_USD · AI_DAILY_LIMIT_CALLS, 구독자는 요금제 한도
2. 계정당 한 달: 비용(USD) — AI_MONTHLY_LIMIT_USD, 구독자는 요금제 한도
3. 서비스 전체 하루: 비용(USD) — AI_GLOBAL_DAILY_LIMIT_USD. 넘으면 모두 잠시 멈추고 운영자에게 메일 한 번
0 이면 그 한도는 없음. 날짜·달은 서비스 시간대(Asia/Seoul) 기준.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.services import billing, learning, mailer

log = logging.getLogger(__name__)

MESSAGE = "오늘 쓸 수 있는 AI 사용량을 모두 썼어요. 오늘 밤 12시에 다시 채워져요"
MONTHLY_MESSAGE = "이번 달 AI 사용량을 모두 썼어요. 다음 달 1일에 다시 채워져요"
GLOBAL_MESSAGE = "지금 AI 를 쓰는 사람이 많아 잠시 쉬고 있어요. 오늘 밤 12시 이후에 다시 이용해 주세요"
_alerted: set[date] = set()  # 서비스 전체 한도 알림은 하루에 한 번


def _local_day(col):
    return func.date(func.timezone(get_settings().timezone, col))


def usage_today(db: Session, user: m.User) -> tuple[float, int]:
    cost, calls = db.execute(select(func.coalesce(func.sum(m.LLMCall.cost_usd), 0), func.count())
                             .where(m.LLMCall.user_id == user.id, _local_day(m.LLMCall.created_at) == learning.local_today(db))).one()
    return float(cost), int(calls)


def usage_month(db: Session, user: m.User) -> float:
    start = learning.local_today(db).replace(day=1)
    return float(db.scalar(select(func.coalesce(func.sum(m.LLMCall.cost_usd), 0))
                           .where(m.LLMCall.user_id == user.id, _local_day(m.LLMCall.created_at) >= start)) or 0)


def usage_global_today(db: Session) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(m.LLMCall.cost_usd), 0))
                           .where(_local_day(m.LLMCall.created_at) == learning.local_today(db))) or 0)


def _wider(plan_value: float, default: float) -> float:
    """기본 한도가 0(제한 없음)이면 구독자도 제한 없음, 아니면 둘 중 넉넉한 쪽"""
    return default and max(plan_value, default)


def limits(db: Session, user: m.User) -> tuple[float, int]:
    """하루 한도 (비용 USD, 호출 수) — 구독 요금제가 있으면 그 한도, 없으면 .env 의 기본값. 0 = 제한 없음"""
    s = get_settings()
    plan = billing.plan_of(db, user)
    if plan.price:
        return _wider(plan.daily_usd, s.ai_daily_limit_usd), int(_wider(plan.daily_calls, s.ai_daily_limit_calls))
    return s.ai_daily_limit_usd, s.ai_daily_limit_calls


def monthly_limit(db: Session, user: m.User) -> float:
    s = get_settings()
    plan = billing.plan_of(db, user)
    return _wider(plan.monthly_usd, s.ai_monthly_limit_usd) if plan.price else s.ai_monthly_limit_usd


def _alert_global(db: Session, spent: float) -> None:
    s = get_settings()
    today = learning.local_today(db)
    if today in _alerted:
        return
    _alerted.add(today)
    log.error("AI 서비스 전체 하루 한도 도달: $%.2f / $%.2f", spent, s.ai_global_daily_limit_usd)
    to = s.feedback_notify_email or next(iter(sorted(s.admins)), None)
    mailer.send_later(to, "[Eureka] 오늘 AI 사용이 서비스 전체 한도에 닿았어요",
                      f"오늘 AI 비용이 ${spent:.2f} 로 서비스 전체 하루 한도(${s.ai_global_daily_limit_usd:.2f})에 닿았어요.\n"
                      "운영자를 뺀 모든 사용자의 AI 기능이 오늘 밤 12시까지 멈춰요.\n"
                      "늘리려면 서버 .env 의 AI_GLOBAL_DAILY_LIMIT_USD 를 바꾸고 앱을 다시 시작하세요.")


def reason(db: Session, user: m.User) -> str | None:
    """AI 를 쓸 수 없는 이유 (쓸 수 있으면 None)"""
    s = get_settings()
    if user.email.lower() in s.admins:
        return None
    if s.ai_global_daily_limit_usd:
        spent = usage_global_today(db)
        if spent >= s.ai_global_daily_limit_usd:
            _alert_global(db, spent)
            return GLOBAL_MESSAGE
    max_usd, max_calls = limits(db, user)
    cost, calls = usage_today(db, user)
    if (max_usd and cost >= max_usd) or (max_calls and calls >= max_calls):
        return MESSAGE
    if (max_month := monthly_limit(db, user)) and usage_month(db, user) >= max_month:
        return MONTHLY_MESSAGE
    return None


def exceeded(db: Session, user: m.User) -> bool:
    return reason(db, user) is not None


def check(db: Session, user: m.User) -> None:
    """한도를 넘었으면 429 (이유와 다시 채워지는 때를 알린다)."""
    if why := reason(db, user):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, why)


def summary(db: Session, user: m.User) -> dict:
    """설정 화면용 — 금액 대신 쓴 비율(%)로 보여 준다"""
    max_usd, max_calls = limits(db, user)
    cost, calls = usage_today(db, user)
    month, max_month = usage_month(db, user), monthly_limit(db, user)
    day_pct = max((cost / max_usd) if max_usd else 0, (calls / max_calls) if max_calls else 0)
    return {
        "unlimited": user.email.lower() in get_settings().admins or not (max_usd or max_calls or max_month),
        "plan": billing.plan_of(db, user).key,
        "today_pct": min(100, round(day_pct * 100)),
        "month_pct": min(100, round((month / max_month) * 100)) if max_month else 0,
        "blocked": reason(db, user),
    }
