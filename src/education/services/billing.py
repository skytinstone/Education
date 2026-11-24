"""월 구독 결제 — PortOne V2 빌링키 정기결제.

흐름
1. 브라우저가 PortOne SDK(requestIssueBillingKey)로 카드를 등록해 빌링키를 받는다 (카드 번호는 우리 서버를 지나지 않는다)
2. POST /billing/subscribe: 빌링키가 이 사용자 것인지 PortOne 에서 확인 → 첫 달 결제 → PortOne 에서 다시 조회해
   금액까지 맞으면 구독을 켜고, 다음 달 결제를 PortOne 에 예약한다
3. 예약 결제가 되면 PortOne 이 웹훅을 보낸다 → 웹훅 내용은 믿지 않고 결제를 다시 조회해 기간을 한 달 늘리고 다음 달을 예약
4. 해지: 예약을 취소하고 이번 기간이 끝날 때까지는 그대로 쓴다. 결제 실패: 3일 동안은 그대로 쓰고 그 뒤 무료로

금액은 항상 서버의 PLANS 에서 정한다 (브라우저가 보낸 금액은 쓰지 않는다).
빌링키는 카드 정보가 아니지만 결제를 일으킬 수 있으므로 암호화해서 저장한다.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from portone_server_sdk import BillingKeyClient, PaymentClient, PaymentScheduleClient
from portone_server_sdk.common import CustomerInput, CustomerNameInput, PaymentAmountInput
from portone_server_sdk.payment import FailedPayment, PaidPayment
from portone_server_sdk.payment.billing_key import BillingKeyPaymentMethodCard, IssuedBillingKeyInfo
from portone_server_sdk.payment.payment_schedule import BillingKeyPaymentScheduleInput
from sqlalchemy import select
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m

log = logging.getLogger(__name__)

GRACE = timedelta(days=3)  # 갱신 결제가 늦거나 실패해도 이 기간은 그대로 쓴다


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price: int              # 원, 부가세 포함 · 한 달
    daily_usd: float        # 하루 AI 비용 한도 (services/quota.py)
    daily_calls: int        # 하루 AI 호출 한도
    perks: tuple[str, ...]


# free 의 한도는 .env 의 AI_DAILY_LIMIT_USD · AI_DAILY_LIMIT_CALLS 를 쓴다 (0 이면 이 값)
PLANS: dict[str, Plan] = {
    "free": Plan("free", "무료", 0, 0, 0, ("하루 AI 사용량 기본 제공", "문제 풀이 · 실전 시험 · AI 면접 체험")),
    "plus": Plan("plus", "Plus", 9900, 3.0, 600, ("무료보다 넉넉한 하루 AI 사용량", "실전 시험 · AI 면접을 자주 볼 때")),
    "pro": Plan("pro", "Pro", 19900, 8.0, 1500, ("Plus 의 2배가 넘는 하루 AI 사용량", "기출 분석 · AI 면접을 매일 할 때")),
}


class BillingError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def available() -> bool:
    s = get_settings()
    return bool(s.portone_store_id and s.portone_channel_key and s.portone_api_secret)


def open_to(user: m.User) -> bool:
    """이 사용자에게 요금제 화면을 보여 줄지 — BILLING_PUBLIC 이 꺼져 있으면(베타) 운영자만"""
    s = get_settings()
    return available() and (s.billing_public or user.email.lower() in s.admins)


# ---------- PortOne 연결 (테스트에서 바꿔 끼운다) ----------
class PortOne:
    def __init__(self) -> None:
        s = get_settings()
        kw = {"secret": s.portone_api_secret or "", "store_id": s.portone_store_id}
        self.payments = PaymentClient(**kw)
        self.billing_keys = BillingKeyClient(**kw)
        self.schedules = PaymentScheduleClient(**kw)


portone_factory = PortOne


def _msg(e: Exception) -> str:
    """PortOne 오류에서 사람이 읽을 메시지를 꺼낸다"""
    for x in (e, getattr(e, "error", None)):
        for attr in ("pg_message", "message"):  # 카드사 메시지(예: 한도 초과)가 있으면 그것부터
            msg = getattr(x, attr, None)
            if isinstance(msg, str) and msg:
                return msg
    return "결제 회사와 연결하지 못했어요"


# ---------- 빌링키 암호화 ----------
def _fernet() -> Fernet:
    key = hashlib.sha256(f"billing-key:{get_settings().jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(key: str) -> str:
    return _fernet().encrypt(key.encode()).decode()


def unseal(sealed: str) -> str:
    return _fernet().decrypt(sealed.encode()).decode()


# ---------- 도움 함수 ----------
def now() -> datetime:
    return datetime.now(UTC)


def add_month(t: datetime) -> datetime:
    """한 달 뒤 같은 날 (1월 31일 → 2월 28·29일)"""
    y, mo = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    return t.replace(year=y, month=mo, day=min(t.day, calendar.monthrange(y, mo)[1]))


def new_payment_id() -> str:
    return f"eu-{uuid.uuid4().hex[:24]}"


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _customer(user: m.User) -> CustomerInput:
    return CustomerInput(id=str(user.id), email=user.email, name=CustomerNameInput(full=user.name) if user.name else None)


def _order_name(plan: Plan) -> str:
    return f"Eureka {plan.name} 1개월"


def card_label(info: IssuedBillingKeyInfo) -> str | None:
    for meth in info.methods or []:
        card = meth.card if isinstance(meth, BillingKeyPaymentMethodCard) else None
        if card:
            digits = "".join(ch for ch in (card.number or "") if ch.isdigit())
            return " ".join(x for x in (card.name or card.issuer or "카드", digits[-4:]) if x)[:80]
    return None


def _is_test(p: PaidPayment) -> bool:
    """PortOne 테스트 채널 결제인지 — 매출 집계에서 뺀다"""
    return (getattr(p.channel, "type", "") or "").upper() == "TEST"


def subscription(db: Session, user: m.User) -> m.Subscription | None:
    return db.scalar(select(m.Subscription).where(m.Subscription.user_id == user.id))


def plan_of(db: Session, user: m.User, at: datetime | None = None) -> Plan:
    """지금 쓸 수 있는 요금제 — 기간이 끝났으면(해지했거나 결제 실패 후 유예도 지났으면) 무료"""
    sub = subscription(db, user)
    if not sub or sub.status == "ended":
        return PLANS["free"]
    t = at or now()
    until = sub.period_end if sub.cancel_at_period_end else sub.period_end + GRACE
    return PLANS.get(sub.plan, PLANS["free"]) if t < until else PLANS["free"]


# ---------- 구독 ----------
def _schedule_next(db: Session, po: PortOne, sub: m.Subscription, user: m.User) -> None:
    """다음 기간 결제를 PortOne 에 예약한다. 실패하면 기록만 남기고 기간이 끝나면 무료가 된다"""
    plan = PLANS[sub.plan]
    pid = new_payment_id()
    try:
        po.schedules.create_payment_schedule(
            payment_id=pid, time_to_pay=_iso(sub.period_end),
            payment=BillingKeyPaymentScheduleInput(billing_key=unseal(sub.billing_key_sealed), order_name=_order_name(plan),
                                                   amount=PaymentAmountInput(total=plan.price), currency="KRW", customer=_customer(user)))
    except Exception as e:  # noqa: BLE001 — 예약 실패는 구독 자체를 막지 않는다
        log.error("billing: schedule failed user=%s: %s", user.id, _msg(e))
        sub.next_payment_id = None
        return
    db.add(m.BillingPayment(id=pid, user_id=user.id, plan=plan.key, amount=plan.price, kind="renewal", status="scheduled", is_test=sub.is_test))
    sub.next_payment_id = pid


def _revoke(db: Session, po: PortOne, sub: m.Subscription) -> None:
    try:
        po.schedules.revoke_payment_schedules(billing_key=unseal(sub.billing_key_sealed))
    except Exception as e:  # noqa: BLE001
        log.warning("billing: revoke failed sub=%s: %s", sub.id, _msg(e))
    if sub.next_payment_id and (p := db.get(m.BillingPayment, sub.next_payment_id)) and p.status == "scheduled":
        p.status = "revoked"
    sub.next_payment_id = None


def subscribe(db: Session, user: m.User, plan_key: str, billing_key: str) -> m.Subscription:
    plan = PLANS.get(plan_key)
    if not plan or not plan.price:
        raise BillingError(422, "없는 요금제예요")
    if not open_to(user):
        raise BillingError(503, "결제는 아직 준비 중이에요")
    if plan_of(db, user).price:
        raise BillingError(409, "이미 구독 중이에요. 요금제를 바꾸려면 해지한 뒤 이번 기간이 끝나고 다시 구독해 주세요")
    po = portone_factory()
    try:
        info = po.billing_keys.get_billing_key_info(billing_key=billing_key)
    except Exception as e:  # noqa: BLE001
        raise BillingError(400, f"카드 등록 정보를 확인하지 못했어요: {_msg(e)}") from e
    if not isinstance(info, IssuedBillingKeyInfo) or (info.customer.id or "") != str(user.id):
        raise BillingError(400, "카드 등록 정보가 맞지 않아요. 다시 시도해 주세요")

    pid = new_payment_id()
    pay = m.BillingPayment(id=pid, user_id=user.id, plan=plan.key, amount=plan.price, kind="first", status="ready")
    db.add(pay)
    db.commit()
    try:
        po.payments.pay_with_billing_key(payment_id=pid, billing_key=billing_key, order_name=_order_name(plan),
                                         customer=_customer(user), amount=PaymentAmountInput(total=plan.price), currency="KRW")
        paid = po.payments.get_payment(payment_id=pid)
    except Exception as e:  # noqa: BLE001
        pay.status, pay.failure = "failed", _msg(e)[:500]
        db.commit()
        raise BillingError(402, f"결제하지 못했어요: {pay.failure}") from e
    if not isinstance(paid, PaidPayment) or paid.amount.total != plan.price:
        pay.status, pay.failure = "failed", "결제 확인 실패 (상태 또는 금액이 맞지 않음)"
        db.commit()
        log.error("billing: first payment mismatch %s: %r", pid, getattr(paid, "status", paid))
        raise BillingError(402, "결제를 확인하지 못했어요. 고객센터로 문의해 주세요")
    pay.status, pay.receipt_url, pay.paid_at = "paid", paid.receipt_url, now()
    pay.is_test = _is_test(paid)

    sub = subscription(db, user)
    old_key = unseal(sub.billing_key_sealed) if sub else None
    if sub:
        _revoke(db, po, sub)
    else:
        sub = m.Subscription(user_id=user.id)
        db.add(sub)
    start = now()
    sub.plan, sub.status, sub.cancel_at_period_end, sub.is_test = plan.key, "active", False, pay.is_test
    sub.billing_key_sealed, sub.card_label = seal(billing_key), card_label(info)
    sub.period_start, sub.period_end = start, add_month(start)
    db.flush()
    _schedule_next(db, po, sub, user)
    db.commit()
    if old_key and old_key != billing_key:  # 예전 카드의 빌링키는 지운다
        try:
            po.billing_keys.delete_billing_key(billing_key=old_key, reason="카드 변경")
        except Exception as e:  # noqa: BLE001
            log.warning("billing: old key delete failed user=%s: %s", user.id, _msg(e))
    return sub


def cancel(db: Session, user: m.User) -> m.Subscription:
    sub = subscription(db, user)
    if not sub or not plan_of(db, user).price:
        raise BillingError(404, "구독 중인 요금제가 없어요")
    if not sub.cancel_at_period_end:
        _revoke(db, portone_factory(), sub)
        sub.cancel_at_period_end = True
        db.commit()
    return sub


def resume(db: Session, user: m.User) -> m.Subscription:
    """해지를 취소 — 이번 기간이 끝나기 전에만"""
    sub = subscription(db, user)
    if not sub or not sub.cancel_at_period_end or now() >= sub.period_end or sub.status != "active":
        raise BillingError(409, "다시 이어 갈 수 있는 구독이 없어요")
    sub.cancel_at_period_end = False
    _schedule_next(db, portone_factory(), sub, user)
    db.commit()
    return sub


def forget(db: Session, user: m.User) -> None:
    """계정을 지울 때 — 예약 결제를 취소하고 빌링키를 지운다 (실패해도 계정 삭제는 막지 않는다)"""
    sub = subscription(db, user)
    if not sub:
        return
    try:
        po = portone_factory()
        key = unseal(sub.billing_key_sealed)
        po.schedules.revoke_payment_schedules(billing_key=key)
        po.billing_keys.delete_billing_key(billing_key=key, reason="회원 탈퇴")
    except Exception as e:  # noqa: BLE001
        log.error("billing: forget failed user=%s: %s", user.id, _msg(e))


def sync_payment(db: Session, payment_id: str) -> str:
    """웹훅으로 알려 온 결제를 PortOne 에서 다시 조회해 반영한다. 몇 번을 불러도 결과가 같다"""
    pay = db.get(m.BillingPayment, payment_id)
    if not pay:
        return "unknown"
    po = portone_factory()
    p = po.payments.get_payment(payment_id=payment_id)
    sub = db.scalar(select(m.Subscription).where(m.Subscription.user_id == pay.user_id)) if pay.user_id else None
    if isinstance(p, PaidPayment):
        if pay.status == "paid":
            return "paid"
        if p.amount.total != pay.amount:
            pay.status, pay.failure = "failed", f"금액 불일치 {p.amount.total} != {pay.amount}"
            log.error("billing: amount mismatch %s", payment_id)
            db.commit()
            return "mismatch"
        pay.status, pay.receipt_url, pay.paid_at = "paid", p.receipt_url, now()
        pay.is_test = _is_test(p)
        if pay.kind == "renewal" and sub and sub.next_payment_id == payment_id:
            sub.period_start, sub.period_end = sub.period_end, add_month(sub.period_end)
            sub.status, sub.next_payment_id = "active", None
            user = db.get(m.User, sub.user_id)
            if user and not sub.cancel_at_period_end:
                _schedule_next(db, po, sub, user)
        db.commit()
        return "paid"
    if isinstance(p, FailedPayment):
        if pay.status != "failed":
            pay.status, pay.failure = "failed", (p.failure.reason or p.failure.pg_message or "결제 실패")[:500]
            if pay.kind == "renewal" and sub and sub.next_payment_id == payment_id:
                sub.status, sub.next_payment_id = "past_due", None
            db.commit()
        return "failed"
    return "pending"


def status(db: Session, user: m.User) -> dict:
    plan = plan_of(db, user)
    sub = subscription(db, user)
    pays = db.scalars(select(m.BillingPayment).where(m.BillingPayment.user_id == user.id, m.BillingPayment.status.in_(("paid", "failed")))
                      .order_by(m.BillingPayment.created_at.desc()).limit(12)).all()
    s = get_settings()
    return {
        "available": open_to(user),
        "store_id": s.portone_store_id if open_to(user) else None,
        "channel_key": s.portone_channel_key if open_to(user) else None,
        "customer_id": str(user.id),
        "plan": plan.key,
        "plans": [{"key": p.key, "name": p.name, "price": p.price, "perks": list(p.perks)} for p in PLANS.values()],
        "subscription": None if not sub or sub.status == "ended" else {
            "plan": sub.plan, "status": sub.status, "card": sub.card_label,
            "period_end": sub.period_end.isoformat(), "cancel_at_period_end": sub.cancel_at_period_end,
            "renews": bool(sub.next_payment_id)},
        "payments": [{"id": p.id, "plan": p.plan, "amount": p.amount, "status": p.status, "kind": p.kind,
                      "receipt_url": p.receipt_url, "failure": p.failure,
                      "at": (p.paid_at or p.created_at).isoformat()} for p in pays],
    }
