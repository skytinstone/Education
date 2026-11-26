"""운영 콘솔 (ADMIN_EMAILS 계정만) — 가입·이용 현황, AI 사용량, 로그인 기록, 계정 관리.

의견·문제 신고(VOC)는 routers/feedback.py 의 /admin/feedback 에 있다.
날짜별 집계는 서비스 시간대(TIMEZONE, 기본 Asia/Seoul) 기준이다.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Select, distinct, func, literal, or_, select, text, union
from sqlalchemy.orm import Session

from education.api.deps import DB, FORCED_PREFIX, AdminUser, admin_user, is_admin
from education.config import get_settings
from education.db import models as m
from education.db.session import session_factory
from education.harness import guardrails, prompts, review
from education.harness.evals import runner as evals
from education.services.llm import get_llm
from education.services import accounts, audit, billing, item_stats, learning

router = APIRouter(prefix="/admin", tags=["운영"], dependencies=[Depends(admin_user)])


def _local_date(column):
    return func.date(func.timezone(get_settings().timezone, column))


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _since_local(db: Session, days: int) -> datetime:
    """서비스 시간대로 '오늘 포함 최근 days 일'의 시작 시각 (UTC)."""
    start = learning.local_today(db) - timedelta(days=days - 1)
    return db.scalar(select(func.timezone(get_settings().timezone, func.cast(literal(start), DateTime()))))


def _fill_days(db: Session, rows: dict[date, dict], days: int, empty: dict) -> list[dict]:
    """빈 날도 0 으로 채운 날짜순 목록."""
    today = learning.local_today(db)
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        out.append({"date": d.isoformat(), **(rows.get(d) or empty)})
    return out


def _cost(x) -> float:
    return round(float(x or 0), 4)


# ---------- 개요 ----------
def _active_users(db: Session, since: datetime) -> int:
    """기간 안에 로그인했거나 문제를 푼 사람 수 (토큰이 7일 유지되므로 풀이 기록도 함께 본다)."""
    ids = union(
        select(m.Attempt.user_id).where(m.Attempt.created_at >= since),
        select(m.LoginEvent.user_id).where(m.LoginEvent.created_at >= since, m.LoginEvent.ok, m.LoginEvent.user_id.is_not(None)),
    ).subquery()
    return db.scalar(select(func.count(distinct(ids.c.user_id)))) or 0


@router.get("/overview")
def overview(db: DB, days: int = Query(30, ge=7, le=180)) -> dict:
    today_start, week_start, month_start = _since_local(db, 1), _since_local(db, 7), _since_local(db, 30)
    users = db.execute(select(
        func.count(),
        func.count().filter(m.User.created_at >= today_start),
        func.count().filter(m.User.created_at >= week_start),
        func.count().filter(m.User.created_at >= month_start),
        func.count().filter(m.User.suspended_at.is_not(None)),
        func.count().filter(m.User.password_hash.is_not(None)),
    )).one()
    providers = dict(db.execute(select(m.OAuthAccount.provider, func.count(distinct(m.OAuthAccount.user_id)))
                                .group_by(m.OAuthAccount.provider)).all())

    day = _local_date(m.User.created_at)
    signups = {d: {"count": n} for d, n in db.execute(
        select(day, func.count()).where(m.User.created_at >= _since_local(db, days)).group_by(day)).all()}

    ai = db.execute(select(
        func.coalesce(func.sum(m.LLMCall.cost_usd).filter(m.LLMCall.created_at >= today_start), 0),
        func.coalesce(func.sum(m.LLMCall.cost_usd).filter(m.LLMCall.created_at >= week_start), 0),
        func.coalesce(func.sum(m.LLMCall.cost_usd), 0),
        func.count(),
        func.count().filter(~m.LLMCall.ok),
    ).where(m.LLMCall.created_at >= month_start)).one()

    voc = dict(db.execute(select(m.Feedback.status, func.count()).where(m.Feedback.status != "resolved")
                          .group_by(m.Feedback.status)).all())
    failed_logins = db.scalar(select(func.count()).where(m.LoginEvent.created_at >= _ago(1), ~m.LoginEvent.ok)) or 0

    return {
        "users": {"total": users[0], "new_today": users[1], "new_7d": users[2], "new_30d": users[3], "suspended": users[4]},
        "sign_in_methods": {"password": users[5], "google": providers.get("google", 0), "kakao": providers.get("kakao", 0)},
        "active": {"dau": _active_users(db, today_start), "wau": _active_users(db, week_start), "mau": _active_users(db, month_start)},
        "signups_by_day": _fill_days(db, signups, days, {"count": 0}),
        "ai": {"cost_today": _cost(ai[0]), "cost_7d": _cost(ai[1]), "cost_30d": _cost(ai[2]), "calls_30d": ai[3], "failed_30d": ai[4],
               "global_limit_usd": get_settings().ai_global_daily_limit_usd},
        "voc": {"open": voc.get("open", 0), "reviewing": voc.get("reviewing", 0)},
        "failed_logins_24h": failed_logins,
        "online_now": db.scalar(select(func.count()).where(m.User.last_seen_at >= datetime.now(timezone.utc) - ONLINE_WITHIN)) or 0,
        "visitors_today": db.scalar(select(func.count()).select_from(m.SiteVisit).where(m.SiteVisit.day == learning.local_today(db))) or 0,
    }


# ---------- AI 사용량 ----------
@router.get("/ai-usage")
def ai_usage(db: DB, days: int = Query(30, ge=1, le=180)) -> dict:
    since = _since_local(db, days)
    L = m.LLMCall
    tokens = L.input_tokens + L.output_tokens
    in_range = L.created_at >= since

    t = db.execute(select(
        func.count(), func.count().filter(~L.ok),
        func.coalesce(func.sum(L.input_tokens), 0), func.coalesce(func.sum(L.cached_tokens), 0),
        func.coalesce(func.sum(L.output_tokens), 0), func.coalesce(func.sum(L.reasoning_tokens), 0),
        func.coalesce(func.sum(L.cost_usd), 0), func.coalesce(func.avg(L.latency_ms).filter(L.ok), 0),
    ).where(in_range)).one()

    day = _local_date(L.created_at)
    by_day = {d: {"calls": c, "cost_usd": _cost(cost), "tokens": int(tok or 0)} for d, c, cost, tok in db.execute(
        select(day, func.count(), func.sum(L.cost_usd), func.sum(tokens)).where(in_range).group_by(day)).all()}

    def grouped(col) -> list[dict]:
        rows = db.execute(select(col, func.count(), func.count().filter(~L.ok), func.sum(L.cost_usd), func.sum(tokens),
                                 func.avg(L.latency_ms).filter(L.ok))
                          .where(in_range).group_by(col).order_by(func.sum(L.cost_usd).desc().nulls_last())).all()
        return [{"key": k, "calls": c, "failed": f, "cost_usd": _cost(cost), "tokens": int(tok or 0), "avg_latency_ms": int(lat or 0)}
                for k, c, f, cost, tok, lat in rows]

    top = db.execute(select(m.User.id, m.User.email, m.User.name, func.count(), func.sum(L.cost_usd))
                     .join(m.User, m.User.id == L.user_id).where(in_range)
                     .group_by(m.User.id).order_by(func.sum(L.cost_usd).desc().nulls_last()).limit(10)).all()
    errors = db.execute(select(L.created_at, L.purpose, L.model, L.error, m.User.email)
                        .outerjoin(m.User, m.User.id == L.user_id)
                        .where(in_range, ~L.ok).order_by(L.created_at.desc()).limit(15)).all()
    return {
        "days": days,
        "totals": {"calls": t[0], "failed": t[1], "input_tokens": int(t[2]), "cached_tokens": int(t[3]),
                   "output_tokens": int(t[4]), "reasoning_tokens": int(t[5]), "cost_usd": _cost(t[6]), "avg_latency_ms": int(t[7])},
        "by_day": _fill_days(db, by_day, days, {"calls": 0, "cost_usd": 0, "tokens": 0}),
        "by_purpose": grouped(L.purpose),
        "by_model": grouped(L.model),
        "top_users": [{"user_id": str(i), "email": e, "name": n, "calls": c, "cost_usd": _cost(cost)} for i, e, n, c, cost in top],
        "recent_errors": [{"at": at.isoformat(), "purpose": p, "model": md, "error": (err or "")[:300], "email": e}
                          for at, p, md, err, e in errors],
    }


# ---------- 로그인 기록 ----------
def _event(e: m.LoginEvent, name: str | None) -> dict:
    return {"id": str(e.id), "at": e.created_at.isoformat(), "user_id": str(e.user_id) if e.user_id else None,
            "email": e.email, "name": name, "method": e.method, "kind": e.kind, "ok": e.ok, "reason": e.reason,
            "ip": e.ip, "user_agent": e.user_agent}


@router.get("/logins")
def logins(db: DB, q: str | None = None, result: str = "all", method: str | None = None, user_id: UUID | None = None,
           before: datetime | None = None, limit: int = Query(100, ge=1, le=500)) -> dict:
    """최근 로그인·가입 기록 (최신순). before 로 이전 페이지를 이어서 받는다. 90일이 지난 기록은 이때 함께 지운다."""
    if audit.purge_old(db):
        db.commit()
    E = m.LoginEvent
    stmt = select(E, m.User.name).outerjoin(m.User, m.User.id == E.user_id).order_by(E.created_at.desc()).limit(limit)
    if result == "ok":
        stmt = stmt.where(E.ok)
    elif result == "fail":
        stmt = stmt.where(~E.ok)
    if method in ("password", "google", "kakao"):
        stmt = stmt.where(E.method == method)
    if user_id:
        stmt = stmt.where(E.user_id == user_id)
    if before:
        stmt = stmt.where(E.created_at < before)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(E.email.ilike(like), E.ip.ilike(like), m.User.name.ilike(like)))
    items = [_event(e, name) for e, name in db.execute(stmt).all()]
    last24 = db.execute(select(func.count().filter(E.ok), func.count().filter(~E.ok)).where(E.created_at >= _ago(1))).one()
    return {"items": items, "last_24h": {"ok": last24[0], "failed": last24[1]}, "retention_days": audit.RETENTION_DAYS}


# ---------- 계정 관리 ----------
def _methods(db: Session, user_ids: list[UUID]) -> dict[UUID, list[str]]:
    out: dict[UUID, list[str]] = {}
    for uid, provider in db.execute(select(m.OAuthAccount.user_id, m.OAuthAccount.provider)
                                    .where(m.OAuthAccount.user_id.in_(user_ids))).all():
        out.setdefault(uid, []).append(provider)
    return out


ONLINE_WITHIN = timedelta(minutes=2)   # 화면이 1분마다 알리므로, 2분 안에 소식이 있으면 '접속 중'
RECENT_WITHIN = timedelta(minutes=15)  # 15분 안이면 '방금 전까지'


def _presence(u: m.User) -> str:
    if not u.last_seen_at:
        return "offline"
    gap = datetime.now(timezone.utc) - u.last_seen_at
    return "online" if gap <= ONLINE_WITHIN else "recent" if gap <= RECENT_WITHIN else "offline"


def _seen(u: m.User) -> dict:
    return {"presence": _presence(u), "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            "last_seen_ip": u.last_seen_ip, "last_seen_ua": u.last_seen_ua, "last_seen_page": u.last_seen_page}


def _user_row(u: m.User, methods: list[str], attempts: int, cost) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None, **_seen(u),
            "suspended_at": u.suspended_at.isoformat() if u.suspended_at else None,
            "methods": (["password"] if u.password_hash else []) + sorted(methods),
            "attempts": attempts, "cost_usd": _cost(cost), "is_admin": is_admin(u)}


@router.get("/users")
def list_users(db: DB, q: str | None = None, state: str = "all", sort: str = "recent",
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    """state: all · online(지금 접속 중) · active · suspended. sort: recent(가입순) · seen(최근 활동) · login · attempts · cost"""
    stmt, total = _users_query(db, q, state, sort)
    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    methods = _methods(db, [u.id for u, *_ in rows])
    return {"total": total, "items": [_user_row(u, methods.get(u.id, []), n, c) for u, n, c in rows]}


def _users_query(db: Session, q: str | None, state: str, sort: str) -> tuple[Select, int]:
    """회원 목록과 CSV 가 같은 검색·필터·정렬을 쓰도록. (User, 푼 문제 수, AI 비용) 행과 전체 수."""
    attempts = select(m.Attempt.user_id, func.count().label("n")).group_by(m.Attempt.user_id).subquery()
    cost = select(m.LLMCall.user_id, func.sum(m.LLMCall.cost_usd).label("c")).group_by(m.LLMCall.user_id).subquery()
    base: Select = select(m.User).outerjoin(attempts, attempts.c.user_id == m.User.id).outerjoin(cost, cost.c.user_id == m.User.id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.where(or_(m.User.email.ilike(like), m.User.name.ilike(like), m.User.last_seen_ip.ilike(like)))
    if state == "online":
        base = base.where(m.User.last_seen_at >= datetime.now(timezone.utc) - ONLINE_WITHIN)
    elif state == "suspended":
        base = base.where(m.User.suspended_at.is_not(None))
    elif state == "active":
        base = base.where(m.User.suspended_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    order = {
        "login": m.User.last_login_at.desc().nulls_last(),
        "seen": m.User.last_seen_at.desc().nulls_last(),
        "attempts": func.coalesce(attempts.c.n, 0).desc(),
        "cost": func.coalesce(cost.c.c, 0).desc(),
    }.get(sort, m.User.created_at.desc())
    return base.add_columns(func.coalesce(attempts.c.n, 0), cost.c.c).order_by(order, m.User.created_at.desc()), total


def _csv_cell(v) -> str:
    """엑셀에서 수식으로 실행되지 않도록 =,+,-,@ 로 시작하는 글자는 앞에 ' 를 붙인다."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/users.csv")
def export_users(db: DB, q: str | None = None, state: str = "all", sort: str = "recent") -> Response:
    """회원 목록 CSV — 화면의 검색·필터·정렬 그대로, 전체 행 (엑셀에서 한글이 깨지지 않게 UTF-8 BOM)."""
    import csv
    import io

    tz = ZoneInfo(get_settings().timezone)
    fmt = lambda t: t.astimezone(tz).strftime("%Y-%m-%d %H:%M") if t else ""  # noqa: E731
    stmt, _ = _users_query(db, q, state, sort)
    rows = db.execute(stmt.limit(10_000)).all()
    methods = _methods(db, [u.id for u, *_ in rows])
    presence = {"online": "접속 중", "recent": "15분 안 활동", "offline": ""}
    names = {"password": "이메일", "google": "Google", "kakao": "카카오"}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["이름", "이메일", "상태", "접속", "가입일", "로그인 방법", "최근 로그인", "마지막 활동", "최근 IP", "기기(브라우저)",
                "푼 문제", "AI 비용(USD)", "이메일 인증", "마케팅 수신", "학교", "전공", "하루 목표", "정지 사유"])
    for u, n, c in rows:
        ms = (["password"] if u.password_hash else []) + sorted(methods.get(u.id, []))
        w.writerow([_csv_cell(x) for x in (
            u.name, u.email, "정지" if u.suspended_at else "운영자" if is_admin(u) else "이용 중", presence[_presence(u)],
            fmt(u.created_at), " · ".join(names.get(k, k) for k in ms), fmt(u.last_login_at), fmt(u.last_seen_at),
            u.last_seen_ip, u.last_seen_ua, n, f"{float(c or 0):.4f}", "인증" if u.email_verified else "미인증",
            "동의" if u.agreed_marketing else "미동의", u.school, u.major, u.daily_goal, u.suspended_reason)])
    stamp = datetime.now(tz).strftime("%Y%m%d-%H%M")
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="eureka-members-{stamp}.csv"', "Cache-Control": "no-store"})


def _action(a: m.AdminAction) -> dict:
    return {"id": str(a.id), "at": a.created_at.isoformat(), "admin_email": a.admin_email, "action": a.action,
            "target_user_id": str(a.target_user_id) if a.target_user_id else None, "target_email": a.target_email,
            "detail": a.detail, "ip": a.ip}


@router.get("/actions")
def admin_actions(db: DB, action: str | None = None, q: str | None = None, before: datetime | None = None,
                  limit: int = Query(100, ge=1, le=500)) -> dict:
    """관리 기록 — 운영자가 한 조치 (최신순). before 로 이전 페이지를 이어서 받는다."""
    A = m.AdminAction
    stmt = select(A).order_by(A.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(A.action == action)
    if before:
        stmt = stmt.where(A.created_at < before)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(A.admin_email.ilike(like), A.target_email.ilike(like), A.detail.ilike(like)))
    counts = dict(db.execute(select(A.action, func.count()).where(A.created_at >= _ago(30)).group_by(A.action)).all())
    return {"items": [_action(a) for a in db.scalars(stmt)], "last_30d": counts}


@router.get("/presence")
def presence(db: DB) -> dict:
    """지금 접속 중(2분 안)과 방금 전까지(15분 안) 접속한 회원 — 운영 콘솔이 15초마다 다시 받는다."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(m.User).where(m.User.last_seen_at >= now - RECENT_WITHIN)
                      .order_by(m.User.last_seen_at.desc()).limit(200)).all()
    today = db.scalar(select(func.count()).where(m.User.last_seen_at >= _since_local(db, 1))) or 0
    items = [{"id": str(u.id), "name": u.name, "email": u.email, **_seen(u)} for u in rows]
    return {"online": sum(x["presence"] == "online" for x in items), "recent": sum(x["presence"] == "recent" for x in items),
            "today": today, "items": items, "at": now.isoformat()}


def _target(db: Session, user_id: UUID) -> m.User:
    user = db.get(m.User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없어요")
    return user


@router.get("/users/{user_id}")
def user_detail(user_id: UUID, db: DB) -> dict:
    u = _target(db, user_id)
    A = m.Attempt
    a = db.execute(select(func.count(), func.count().filter(A.correct), func.max(A.created_at)).where(A.user_id == u.id)).one()
    ai = db.execute(select(func.count(), func.sum(m.LLMCall.cost_usd)).where(m.LLMCall.user_id == u.id)).one()
    count = lambda model: db.scalar(select(func.count()).select_from(model).where(model.user_id == u.id)) or 0  # noqa: E731
    open_notes = db.scalar(select(func.count()).where(m.WrongNote.user_id == u.id, m.WrongNote.resolved_at.is_(None))) or 0
    events = db.scalars(select(m.LoginEvent).where(m.LoginEvent.user_id == u.id).order_by(m.LoginEvent.created_at.desc()).limit(20))
    feedback = db.scalars(select(m.Feedback).where(m.Feedback.user_id == u.id).order_by(m.Feedback.created_at.desc()).limit(20))
    E = m.LoginEvent
    ips = db.execute(select(E.ip, func.count(), func.max(E.created_at), func.count().filter(~E.ok))
                     .where(E.user_id == u.id, E.ip.is_not(None)).group_by(E.ip)
                     .order_by(func.max(E.created_at).desc()).limit(20)).all()
    return {
        "user": {**_user_row(u, _methods(db, [u.id]).get(u.id, []), a[0], ai[1]),
                 "email_verified": u.email_verified, "daily_goal": u.daily_goal, "agreed_marketing": u.agreed_marketing,
                 "school": u.school, "major": u.major, "birth_date": u.birth_date.isoformat() if u.birth_date else None,
                 "suspended_reason": u.suspended_reason},
        "learning": {"attempts": a[0], "correct": a[1], "accuracy": (a[1] / a[0]) if a[0] else None,
                     "last_attempt_at": a[2].isoformat() if a[2] else None, "today": learning.today_count(db, u),
                     "streak": learning.streak(db, u), "open_notes": open_notes, "projects": count(m.Project),
                     "sessions": count(m.ChatSession), "cards": count(m.Card), "materials": count(m.Material)},
        "ai": {"calls": ai[0], "cost_usd": _cost(ai[1])},
        "logins": [_event(e, u.name) for e in events],
        "ips": [{"ip": ip, "logins": n, "failed": f, "last_at": at.isoformat()} for ip, n, at, f in ips],
        "actions": [_action(a) for a in db.scalars(select(m.AdminAction).where(m.AdminAction.target_user_id == u.id)
                                                   .order_by(m.AdminAction.created_at.desc()).limit(20))],
        "feedback": [{"id": str(f.id), "kind": f.kind, "status": f.status, "message": f.message[:300],
                      "created_at": f.created_at.isoformat()} for f in feedback],
    }


class SuspendIn(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class AdminDeleteIn(BaseModel):
    confirm_email: str


def _guard(target: m.User) -> None:
    if is_admin(target):
        raise HTTPException(status.HTTP_409_CONFLICT, "운영자 계정은 여기서 정지하거나 삭제할 수 없어요 (ADMIN_EMAILS 에서 먼저 빼 주세요)")


@router.post("/users/{user_id}/suspend")
def suspend(user_id: UUID, body: SuspendIn, db: DB, request: Request, me: AdminUser) -> dict:
    """이용 정지 — 로그인과 모든 API 가 바로 막힌다 (이미 받은 로그인 토큰도)."""
    u = _target(db, user_id)
    _guard(u)
    u.suspended_at, u.suspended_reason = datetime.now(timezone.utc), body.reason.strip()
    audit.log_admin(db, request, me, "suspend", u, body.reason.strip())
    db.commit()
    return user_detail(user_id, db)


@router.post("/users/{user_id}/unsuspend")
def unsuspend(user_id: UUID, db: DB, request: Request, me: AdminUser) -> dict:
    u = _target(db, user_id)
    u.suspended_at = u.suspended_reason = None
    audit.log_admin(db, request, me, "unsuspend", u)
    db.commit()
    return user_detail(user_id, db)


class LogoutIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post("/users/{user_id}/logout")
def force_logout(user_id: UUID, body: LogoutIn, db: DB, request: Request, me: AdminUser) -> dict:
    """강제 로그아웃 — 그 회원이 쓰던 모든 곳의 로그인을 끊는다 (화면은 다음 요청, 길어도 1분 안에 로그아웃).
    계정은 그대로라 다시 로그인하면 쓸 수 있다. 도용이 의심되면 이용 정지와 함께 쓴다."""
    u = _target(db, user_id)
    if u.id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "내 계정은 여기서 로그아웃할 수 없어요")
    u.session_id = FORCED_PREFIX + secrets.token_hex(15)
    audit.log_admin(db, request, me, "logout", u, (body.reason or "").strip() or None)
    db.commit()
    return user_detail(user_id, db)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: UUID, body: AdminDeleteIn, db: DB, request: Request, me: AdminUser) -> Response:
    """계정 삭제 — 회원 탈퇴와 똑같이 학습 기록·올린 파일·프로필 사진까지 지운다. 실수 방지로 이메일을 한 번 더 받는다."""
    u = _target(db, user_id)
    _guard(u)
    if body.confirm_email.strip().lower() != u.email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "이메일이 맞지 않아요")
    audit.log_admin(db, request, me, "delete", u, u.name)
    accounts.delete_account(db, u)  # 여기서 함께 커밋된다
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 문제 품질: AI 가 만든 문제의 통과율 · 탈락 이유 · 개념별 ----------
@router.get("/quality")
def quality(db: DB, days: int = Query(30, ge=1, le=180)) -> dict:
    since = _since_local(db, days)
    P, PC = m.Problem, m.ProblemConcept
    made = (P.source == "generated") & (P.created_at >= since)
    ok = P.verification == "verified"
    total, passed = db.execute(select(func.count(), func.count().filter(ok)).where(made)).one()

    reason = func.split_part(P.generation_meta["reject_reason"].astext, ":", 1)
    reasons = [{"reason": r or "기타", "count": n} for r, n in db.execute(
        select(reason, func.count()).where(made, ~ok).group_by(reason).order_by(func.count().desc())).all()]

    day = _local_date(P.created_at)
    daily = {d: {"total": t, "passed": p} for d, t, p in db.execute(
        select(day, func.count(), func.count().filter(ok)).where(made).group_by(day)).all()}

    by_concept = db.execute(
        select(PC.concept_id, m.Concept.name, func.count(), func.count().filter(ok))
        .join(P, P.id == PC.problem_id).join(m.Concept, m.Concept.id == PC.concept_id)
        .where(made).group_by(PC.concept_id, m.Concept.name).having(func.count() >= 3)
        .order_by((func.count().filter(ok) * 1.0 / func.count()).asc()).limit(10)).all()

    keys = dict(db.execute(select(m.ProblemAnswer.status, func.count()).where(m.ProblemAnswer.status.is_not(None))
                           .group_by(m.ProblemAnswer.status)).all())
    reports = db.scalar(select(func.count()).select_from(m.Feedback).where(
        m.Feedback.kind.in_(("problem", "solution")), m.Feedback.created_at >= since)) or 0
    return {
        "days": days,
        "generated": {"total": total, "passed": passed, "rate": (passed / total) if total else None},
        "reasons": reasons,
        "by_day": _fill_days(db, daily, min(days, 60), {"total": 0, "passed": 0}),
        "weak_concepts": [{"concept_id": c, "name": n, "total": t, "passed": p, "rate": p / t} for c, n, t, p in by_concept],
        "answer_keys": keys,
        "reports": reports,
    }


# ---------- 문제 성적표: 학생 실력을 감안한 문항 분석 ----------
@router.get("/item-stats")
def item_stats_list(db: DB, flag: str | None = None, grade: str | None = Query(None, pattern="^[ABCD]$")) -> dict:
    return item_stats.summary(db, flag=flag, grade=grade)


@router.post("/item-stats/refresh")
def item_stats_refresh(db: DB) -> dict:
    """처음 풀이 기록으로 모든 문제 성적을 다시 계산한다 (매일 아침 알림 작업에서도 한다)."""
    out = item_stats.refresh(db)
    db.commit()
    return out


# ---------- 하네스: AI 실행 기록 · 지시문 버전 ----------
@router.get("/harness")
def harness_overview(db: DB, days: int = Query(30, ge=1, le=180)) -> dict:
    """지금 하네스 버전 · 지시문 버전 · 모델, 그리고 버전별 실행 결과 (통과율 · 평균 비용 · 평균 시간)."""
    since = _since_local(db, days)
    R = m.AgentRun
    rows = db.execute(
        select(R.harness_version, R.kind, R.status, func.count(), func.avg(R.cost_usd), func.avg(R.latency_ms), func.min(R.created_at))
        .where(R.created_at >= since).group_by(R.harness_version, R.kind, R.status)).all()
    by_version: dict = {}
    for ver, kind, st, n, cost, ms, first in rows:
        v = by_version.setdefault((ver, kind), {"harness_version": ver, "kind": kind, "runs": 0, "statuses": {}, "cost": 0.0,
                                               "latency": 0.0, "first_at": first})
        v["runs"] += n
        v["statuses"][st] = n
        v["cost"] += float(cost or 0) * n
        v["latency"] += float(ms or 0) * n
        v["first_at"] = min(v["first_at"], first)
    versions = []
    for v in by_version.values():
        versions.append({**v, "avg_cost_usd": v.pop("cost") / v["runs"], "avg_latency_ms": v.pop("latency") / v["runs"],
                         "first_at": v["first_at"].isoformat()})
    versions.sort(key=lambda v: v["first_at"], reverse=True)
    week = _since_local(db, 7)
    guard: dict = {}
    for kind, flags in db.execute(select(m.GuardEvent.kind, m.GuardEvent.flags).where(m.GuardEvent.created_at >= week)):
        for f in flags:
            guard[f"{kind}:{f}"] = guard.get(f"{kind}:{f}", 0) + 1
    policy = db.scalar(select(func.count()).select_from(m.AgentRun).where(
        m.AgentRun.created_at >= week, m.AgentRun.output.like("규칙 위반%"))) or 0
    return {"harness_version": prompts.harness_version(), "models": prompts.models(), "prompts": prompts.versions(),
            "days": days, "versions": versions,
            "guard": {"input_7d": guard, "policy_rejects_7d": policy, "breakers": guardrails.BREAKER.state()},
            "review": review.counts(db)}


@router.get("/runs")
def list_runs(db: DB, kind: str | None = None, status: str | None = None, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    R = m.AgentRun
    q = select(R, m.User.email).outerjoin(m.User, m.User.id == R.user_id).order_by(R.created_at.desc()).limit(limit)
    if kind:
        q = q.where(R.kind == kind)
    if status:
        q = q.where(R.status == status)
    return [{"id": str(r.id), "kind": r.kind, "status": r.status, "email": email, "problem_id": r.problem_id,
             "harness_version": r.harness_version, "input": r.input[:120], "output": r.output[:120],
             "steps": len(r.steps), "tools": sum(1 for x in r.steps if x["name"].startswith("tool:")),
             "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None, "latency_ms": r.latency_ms,
             "created_at": r.created_at.isoformat()} for r, email in db.execute(q)]


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, db: DB) -> dict:
    r = db.get(m.AgentRun, run_id)
    if r is None:
        raise HTTPException(404, "실행 기록을 찾을 수 없어요")
    email = db.scalar(select(m.User.email).where(m.User.id == r.user_id)) if r.user_id else None
    return {"id": str(r.id), "kind": r.kind, "status": r.status, "email": email, "problem_id": r.problem_id,
            "harness_version": r.harness_version, "prompt_versions": r.prompt_versions, "input": r.input, "output": r.output,
            "steps": r.steps, "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None, "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat()}


# ---------- 하네스 평가 (골든셋 점수판) ----------
def _eval_summary(r: m.EvalRun) -> dict:
    return {"id": str(r.id), "harness_version": r.harness_version, "mode": r.mode, "status": r.status, "suites": r.suites, "models": r.models,
            "metrics": r.metrics, "error": r.error, "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
            "latency_ms": r.latency_ms, "created_at": r.created_at.isoformat()}


@router.get("/evals")
def list_evals(db: DB, limit: int = Query(30, ge=1, le=100)) -> list[dict]:
    return [_eval_summary(r) for r in db.scalars(select(m.EvalRun).order_by(m.EvalRun.created_at.desc()).limit(limit))]


@router.get("/evals/{eval_id}")
def get_eval(eval_id: UUID, db: DB) -> dict:
    r = db.get(m.EvalRun, eval_id)
    if r is None:
        raise HTTPException(404, "평가 기록을 찾을 수 없어요")
    return {**_eval_summary(r), "cases": r.cases, "prompt_versions": r.prompt_versions, "models": r.models}


def _run_eval_in_background(open_session, eval_id: UUID) -> None:
    with open_session() as db:
        row = db.get(m.EvalRun, eval_id)
        try:
            evals.run(db, llm=get_llm(), mode="live", eval_run=row, suites=tuple(row.suites))
        except Exception as e:  # 평가가 실패해도 기록은 남긴다
            db.rollback()
            row = db.get(m.EvalRun, eval_id)
            row.status, row.error = "failed", f"{type(e).__name__}: {e}"[:1000]
        db.commit()


@router.post("/evals/run", status_code=status.HTTP_202_ACCEPTED)
def start_eval(db: DB, background: BackgroundTasks, open_session=Depends(session_factory)) -> dict:
    """실제 AI 로 골든셋 평가를 돌린다 (몇 분 · 약 $1 안팎). 이미 도는 평가가 있으면 그것을 돌려준다."""
    if get_llm() is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    # 서버가 다시 시작되며 끊긴 평가(30분 넘게 running)는 무시한다
    running = db.scalar(select(m.EvalRun).where(m.EvalRun.status == "running", m.EvalRun.mode == "live",
                                                m.EvalRun.created_at > func.now() - timedelta(minutes=30)))
    if running:
        return _eval_summary(running)
    row = m.EvalRun(harness_version=prompts.harness_version(), mode="live", status="running",
                    suites=["verify", "retrieval", "generate", "reviewed"],
                    prompt_versions=prompts.versions(), models=prompts.models())
    db.add(row)
    db.commit()
    background.add_task(_run_eval_in_background, open_session, row.id)
    return _eval_summary(row)


# ---------- 사람 검토 큐 ----------
class ReviewDecision(BaseModel):
    action: str = Field(pattern="^(keep|fix|hide)$")
    answer: str | None = Field(None, max_length=20)
    note: str = Field("", max_length=1000)


def _review_out(it: m.ReviewItem, p: m.Problem, stats: m.ProblemStats | None, email: str | None) -> dict:
    return {"id": str(it.id), "status": it.status, "source": it.source, "source_name": review.SOURCE_NAME.get(it.source, it.source),
            "reason": it.reason, "note": it.note, "created_at": it.created_at.isoformat(),
            "decided_at": it.decided_at.isoformat() if it.decided_at else None, "decided_by": email,
            "answer_before": it.answer_before, "answer_after": it.answer_after,
            "problem": {"id": p.id, "stem": p.stem, "choices": p.choices, "answer": p.answer, "solution": p.solution,
                        "domain": p.domain, "source": p.source, "verification": p.verification,
                        "concepts": [c.name for c in p.concepts]},
            "stats": {"grade": stats.grade, "n": stats.n, "p": stats.p, "flags": stats.flags} if stats else None}


@router.get("/review")
def list_review(db: DB, status_: str = Query("open", alias="status", pattern="^(open|decided)$"), limit: int = Query(50, ge=1, le=200)) -> dict:
    R = m.ReviewItem
    q = (select(R, m.Problem, m.ProblemStats, m.User.email).join(m.Problem, m.Problem.id == R.problem_id)
         .outerjoin(m.ProblemStats, m.ProblemStats.problem_id == R.problem_id).outerjoin(m.User, m.User.id == R.decided_by))
    q = q.where(R.status == "open").order_by(R.created_at) if status_ == "open" else q.where(R.status != "open").order_by(R.decided_at.desc())
    return {"counts": review.counts(db), "items": [_review_out(*row) for row in db.execute(q.limit(limit))]}


@router.post("/review/{item_id}/decide")
def decide_review(item_id: UUID, body: ReviewDecision, db: DB, request: Request, me: AdminUser) -> dict:
    it = db.get(m.ReviewItem, item_id)
    if it is None:
        raise HTTPException(404, "검토 항목을 찾을 수 없어요")
    try:
        review.decide(db, it, me, body.action, answer=body.answer, note=body.note)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    audit.log_admin(db, request, me, f"review_{body.action}", None,
                    f"문제 {it.problem_id} · {it.answer_before} → {it.answer_after or it.answer_before} · {body.note}")
    db.commit()
    p = db.get(m.Problem, it.problem_id)
    return _review_out(it, p, db.get(m.ProblemStats, p.id), me.email)


# ---------- 가입 전환 퍼널 · 주간 재방문 ----------
FUNNEL_SQL = text("""
WITH cohort AS (
  SELECT u.id, date(timezone(:tz, u.created_at)) AS joined
  FROM users u WHERE u.created_at >= :since
), activity AS (
  SELECT user_id, date(timezone(:tz, created_at)) AS day FROM attempts WHERE created_at >= :since
  UNION
  SELECT user_id, date(timezone(:tz, created_at)) FROM login_events WHERE ok AND user_id IS NOT NULL AND created_at >= :since
)
SELECT
  (SELECT count(DISTINCT visitor_id) FROM site_visits WHERE day >= date(timezone(:tz, :since))) AS visitors,
  (SELECT count(*) FROM cohort) AS signups,
  (SELECT count(*) FROM cohort c WHERE EXISTS (SELECT 1 FROM attempts a WHERE a.user_id = c.id)) AS activated,
  (SELECT count(*) FROM cohort c WHERE EXISTS (SELECT 1 FROM activity x WHERE x.user_id = c.id AND x.day > c.joined)) AS returned
""")

COHORT_SQL = text("""
WITH cohort AS (
  SELECT u.id, date_trunc('week', timezone(:tz, u.created_at))::date AS week
  FROM users u WHERE u.created_at >= :since
), activity AS (
  SELECT user_id, timezone(:tz, created_at)::date AS day FROM attempts WHERE created_at >= :since
  UNION
  SELECT user_id, timezone(:tz, created_at)::date FROM login_events WHERE ok AND user_id IS NOT NULL AND created_at >= :since
)
SELECT c.week, count(*) AS size,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM activity a WHERE a.user_id = c.id
                                      AND a.day >= c.week + 7 AND a.day < c.week + 14)) AS week1
FROM cohort c GROUP BY c.week ORDER BY c.week
""")


@router.get("/funnel")
def funnel(db: DB, days: int = Query(30, ge=7, le=180)) -> dict:
    """방문 → 가입 → 첫 문제 → 다음 날 이후 다시 옴. 주간 가입 묶음별로 다음 주에도 쓴 비율."""
    since = _since_local(db, days)
    tz = get_settings().timezone
    v = db.execute(FUNNEL_SQL, {"tz": tz, "since": since}).one()
    cohorts = db.execute(COHORT_SQL, {"tz": tz, "since": _since_local(db, 7 * 8)}).all()
    return {
        "days": days,
        "steps": [{"key": "visitors", "label": "방문", "count": v.visitors},
                  {"key": "signups", "label": "가입", "count": v.signups},
                  {"key": "activated", "label": "첫 문제 풀이", "count": v.activated},
                  {"key": "returned", "label": "다른 날 다시 옴", "count": v.returned}],
        "cohorts": [{"week": w.isoformat(), "size": n, "week1": k, "rate": (k / n) if n else None} for w, n, k in cohorts],
    }


# ---------- 매출 (월 구독 결제) ----------
def _month_start(d: date) -> date:
    return d.replace(day=1)


@router.get("/revenue")
def revenue(db: DB, days: int = Query(30, ge=1, le=365), include_test: bool = False) -> dict:
    """결제 · 구독 · AI 원가 · 마진. 금액은 원(부가세 포함), AI 비용은 USD 를 usd_krw 로 환산한 추정치."""
    s = get_settings()
    P, S, L = m.BillingPayment, m.Subscription, m.LLMCall
    live = (lambda col: col.is_(False)) if not include_test else (lambda col: literal(True))
    since = _since_local(db, days)
    paid_in = (P.status == "paid") & (P.paid_at >= since) & live(P.is_test)

    gross, n_paid = db.execute(select(func.coalesce(func.sum(P.amount), 0), func.count()).where(paid_in)).one()
    n_failed = db.scalar(select(func.count()).where(P.status == "failed", P.created_at >= since, live(P.is_test))) or 0
    first = db.scalar(select(func.count()).where(paid_in, P.kind == "first")) or 0

    # 이번 달 · 지난달 (서비스 시간대 달력)
    today = learning.local_today(db)
    this_m = _month_start(today)
    last_m = _month_start(this_m - timedelta(days=1))
    pday = _local_date(P.paid_at)
    def month_sum(a: date, b: date) -> int:
        return int(db.scalar(select(func.coalesce(func.sum(P.amount), 0)).where(
            P.status == "paid", live(P.is_test), pday >= a, pday < b)) or 0)
    this_month, last_month = month_sum(this_m, today + timedelta(days=1)), month_sum(last_m, this_m)

    # 지금 구독 중 (해지 예약 포함) · MRR (해지 예약은 빼고)
    now = billing.now()
    subs = db.scalars(select(S).where(S.status != "ended", live(S.is_test))).all()
    active = [x for x in subs if now < (x.period_end if x.cancel_at_period_end else x.period_end + billing.GRACE)]
    plans = {k: {"name": p.name, "price": p.price, "active": 0, "canceling": 0} for k, p in billing.PLANS.items() if p.price}
    for x in active:
        if x.plan in plans:
            plans[x.plan]["canceling" if x.cancel_at_period_end else "active"] += 1
    mrr = sum(v["price"] * v["active"] for v in plans.values())
    past_due = sum(1 for x in active if x.status == "past_due")
    canceling = sum(v["canceling"] for v in plans.values())

    # 원가: 같은 기간 AI 비용 전체 · 구독자 몫
    ai_usd = float(db.scalar(select(func.coalesce(func.sum(L.cost_usd), 0)).where(L.created_at >= since)) or 0)
    sub_users = [x.user_id for x in active]
    ai_sub_usd = float(db.scalar(select(func.coalesce(func.sum(L.cost_usd), 0)).where(
        L.created_at >= since, L.user_id.in_(sub_users))) or 0) if sub_users else 0.0
    gross = int(gross)
    net = round(gross / 1.1 * (1 - s.pg_fee_rate))  # 부가세 · 결제 수수료를 뺀 추정
    ai_krw = round(ai_usd * s.usd_krw)

    by_day = {d: {"amount": int(a or 0), "count": c} for d, a, c in db.execute(
        select(pday, func.sum(P.amount), func.count()).where(paid_in).group_by(pday)).all()}
    recent = db.execute(select(P, m.User.email).outerjoin(m.User, m.User.id == P.user_id)
                        .where(P.status.in_(("paid", "failed")), live(P.is_test))
                        .order_by(P.created_at.desc()).limit(20)).all()
    return {
        "days": days, "include_test": include_test, "usd_krw": s.usd_krw, "pg_fee_rate": s.pg_fee_rate,
        "totals": {"gross": gross, "net_estimate": net, "payments": n_paid, "failed": n_failed, "new_subscriptions": first,
                   "ai_cost_usd": round(ai_usd, 4), "ai_cost_krw": ai_krw, "margin_krw": net - ai_krw,
                   "margin_rate": round((net - ai_krw) / net, 4) if net else None},
        "months": {"this": this_month, "last": last_month},
        "subscriptions": {"mrr": mrr, "active": sum(v["active"] for v in plans.values()), "canceling": canceling,
                          "past_due": past_due, "by_plan": [{"key": k, **v} for k, v in plans.items()],
                          "ai_cost_per_subscriber_krw": round(ai_sub_usd * s.usd_krw / len(active)) if active else None},
        "by_day": _fill_days(db, by_day, days, {"amount": 0, "count": 0}),
        "recent": [{"id": p.id, "email": e, "plan": p.plan, "amount": p.amount, "kind": p.kind, "status": p.status,
                    "failure": p.failure, "receipt_url": p.receipt_url, "is_test": p.is_test,
                    "at": (p.paid_at or p.created_at).isoformat()} for p, e in recent],
    }
