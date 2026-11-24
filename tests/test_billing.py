"""월 구독 결제 (services/billing.py · /api/billing) — PortOne 은 가짜로 바꿔 끼우고, 응답은 SDK 의 실제 파서로 만든다."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from portone_server_sdk._generated.payment.billing_key.billing_key_info import _deserialize_billing_key_info
from portone_server_sdk._generated.payment.payment import _deserialize_payment

from education.config import get_settings
from education.db import models as m
from education.services import billing, quota

T = "2026-11-24T00:00:00Z"
CH = {"type": "TEST", "id": "ch", "key": "ck", "name": "토스페이먼츠", "pgProvider": "TOSSPAYMENTS", "pgMerchantId": "m"}
WHSEC = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


def payment_json(pid, status="PAID", total=9900):
    base = {"id": pid, "transactionId": "tx", "merchantId": "mer", "storeId": "store", "channel": CH, "version": "V2",
            "requestedAt": T, "updatedAt": T, "statusChangedAt": T, "orderName": "Eureka", "currency": "KRW",
            "amount": {"total": total, "taxFree": 0, "discount": 0, "paid": total, "cancelled": 0, "cancelledTaxFree": 0},
            "customer": {"id": "u"}, "origin": {"platformType": "API", "ipAddress": "1.1.1.1"}}
    if status == "PAID":
        return {**base, "status": "PAID", "paidAt": T, "disputes": [], "receiptUrl": f"https://receipt/{pid}"}
    return {**base, "status": "FAILED", "failedAt": T, "failure": {"reason": "잔액 부족"}}


class Declined(Exception):
    """PortOne 결제 오류처럼 message · pg_message 를 가진 예외"""
    message = "결제에 실패했습니다"
    pg_message = "카드 한도 초과"


class FakePortOne:
    """PortOne 의 세 클라이언트를 흉내 — 호출을 기록하고, 결제 결과는 outcome 으로 정한다"""
    outcome: dict = {}
    calls: list = []
    owner: str = ""

    def __init__(self):
        self.payments = self.billing_keys = self.schedules = self

    def get_billing_key_info(self, *, billing_key):
        FakePortOne.calls.append(("info", billing_key))
        return _deserialize_billing_key_info({
            "status": "ISSUED", "billingKey": billing_key, "merchantId": "mer", "storeId": "store", "channels": [CH],
            "customer": {"id": FakePortOne.owner}, "issuedAt": T,
            "methods": [{"type": "BillingKeyPaymentMethodCard", "card": {"name": "신한카드", "number": "123456******4321"}}]})

    def pay_with_billing_key(self, *, payment_id, billing_key, amount, **kw):
        FakePortOne.calls.append(("pay", payment_id, amount.total))
        if FakePortOne.outcome.get(payment_id, "PAID") == "DECLINE":
            raise Declined()

    def get_payment(self, *, payment_id):
        o = FakePortOne.outcome.get(payment_id, "PAID")
        total = 100 if o == "WRONG_AMOUNT" else FakePortOne.outcome.get(("total", payment_id), 9900)
        return _deserialize_payment(payment_json(payment_id, "FAILED" if o == "FAILED" else "PAID", total))

    def create_payment_schedule(self, *, payment_id, payment, time_to_pay):
        FakePortOne.calls.append(("schedule", payment_id, payment.amount.total, time_to_pay))

    def revoke_payment_schedules(self, *, billing_key):
        FakePortOne.calls.append(("revoke", billing_key))

    def delete_billing_key(self, *, billing_key, reason=None):
        FakePortOne.calls.append(("delete", billing_key))


@pytest.fixture
def portone(monkeypatch):
    s = get_settings()
    for k, v in {"portone_store_id": "store-test", "portone_channel_key": "channel-test", "portone_api_secret": "secret",
                 "portone_webhook_secret": WHSEC}.items():
        monkeypatch.setattr(s, k, v)
    FakePortOne.outcome, FakePortOne.calls = {}, []
    monkeypatch.setattr(billing, "portone_factory", FakePortOne)
    return FakePortOne


def me(client, auth):
    return client.get("/api/billing", headers=auth).json()


def subscribe(client, auth, plan="plus", key="billing-key-1"):
    FakePortOne.owner = me(client, auth)["customer_id"]
    return client.post("/api/billing/subscribe", json={"plan": plan, "billing_key": key}, headers=auth)


def signed(body: dict) -> tuple[str, dict]:
    payload = json.dumps(body)
    mid, ts = "msg_1", str(int(time.time()))
    sig = hmac.new(base64.b64decode(WHSEC.removeprefix("whsec_")), f"{mid}.{ts}.{payload}".encode(), hashlib.sha256).digest()
    return payload, {"webhook-id": mid, "webhook-timestamp": ts, "webhook-signature": "v1," + base64.b64encode(sig).decode(),
                     "content-type": "application/json"}


def paid_event(pid):
    return {"type": "Transaction.Paid", "timestamp": T, "data": {"storeId": "store", "paymentId": pid, "transactionId": "tx"}}


def test_hidden_until_configured(client, auth):
    d = me(client, auth)
    assert d["available"] is False and d["plan"] == "free" and d["store_id"] is None
    assert [p["key"] for p in d["plans"]] == ["free", "plus", "pro"]


def test_subscribe_charges_server_price_and_schedules_next(client, auth, portone, db):
    r = subscribe(client, auth)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plan"] == "plus" and d["subscription"]["card"] == "신한카드 4321" and d["subscription"]["renews"]
    pay = next(c for c in portone.calls if c[0] == "pay")
    assert pay[2] == 9900  # 금액은 서버의 요금제에서
    sched = next(c for c in portone.calls if c[0] == "schedule")
    assert sched[2] == 9900 and sched[3].endswith("Z")
    sub = db.query(m.Subscription).one()
    assert sub.billing_key_sealed != "billing-key-1" and billing.unseal(sub.billing_key_sealed) == "billing-key-1"
    assert d["payments"][0]["status"] == "paid" and d["payments"][0]["receipt_url"].startswith("https://receipt/")
    # 이미 구독 중이면 다시 결제하지 않는다
    assert subscribe(client, auth, "pro").status_code == 409


def test_rejects_someone_elses_billing_key(client, auth, portone):
    FakePortOne.owner = "someone-else"
    r = client.post("/api/billing/subscribe", json={"plan": "plus", "billing_key": "billing-key-x"}, headers=auth)
    assert r.status_code == 400 and not any(c[0] == "pay" for c in portone.calls)


def test_declined_or_mismatched_payment_does_not_activate(client, auth, portone, monkeypatch):
    ids = iter(["eu-decline", "eu-wrong"])
    monkeypatch.setattr(billing, "new_payment_id", lambda: next(ids))
    portone.outcome = {"eu-decline": "DECLINE", "eu-wrong": "WRONG_AMOUNT"}
    r = subscribe(client, auth)
    assert r.status_code == 402 and "한도 초과" in r.json()["detail"]
    assert subscribe(client, auth).status_code == 402
    d = me(client, auth)
    assert d["plan"] == "free" and d["subscription"] is None and {p["status"] for p in d["payments"]} == {"failed"}


def test_cancel_keeps_until_period_end_then_resume(client, auth, portone, db):
    subscribe(client, auth)
    d = client.post("/api/billing/cancel", headers=auth).json()
    assert d["subscription"]["cancel_at_period_end"] and not d["subscription"]["renews"] and d["plan"] == "plus"
    assert ("revoke", "billing-key-1") in portone.calls
    user = db.query(m.User).one()
    sub = db.query(m.Subscription).one()
    assert billing.plan_of(db, user, at=sub.period_end + timedelta(seconds=1)).key == "free"  # 해지하면 유예 없음
    d = client.post("/api/billing/resume", headers=auth).json()
    assert not d["subscription"]["cancel_at_period_end"] and d["subscription"]["renews"]


def test_webhook_renewal_extends_period_and_failure_gives_grace(client, auth, portone, db):
    subscribe(client, auth)
    sub = db.query(m.Subscription).one()
    first_end, renewal = sub.period_end, sub.next_payment_id
    # 서명이 틀리면 거절
    payload, headers = signed(paid_event(renewal))
    assert client.post("/api/billing/webhook", content=payload, headers={**headers, "webhook-signature": "v1,AAAA"}).status_code == 400
    r = client.post("/api/billing/webhook", content=payload, headers=headers)
    assert r.status_code == 200 and r.json()["result"] == "paid"
    db.refresh(sub)
    assert sub.period_start == first_end and sub.period_end == billing.add_month(first_end) and sub.next_payment_id != renewal
    # 같은 웹훅이 다시 와도 기간을 두 번 늘리지 않는다
    client.post("/api/billing/webhook", content=payload, headers=headers)
    db.refresh(sub)
    assert sub.period_end == billing.add_month(first_end)
    # 다음 달 결제 실패 → past_due, 기간 끝 + 3일까지는 Plus
    nxt = sub.next_payment_id
    portone.outcome[nxt] = "FAILED"
    payload, headers = signed({**paid_event(nxt), "type": "Transaction.Failed"})
    assert client.post("/api/billing/webhook", content=payload, headers=headers).json()["result"] == "failed"
    db.refresh(sub)
    user = db.query(m.User).one()
    assert sub.status == "past_due" and sub.next_payment_id is None
    assert billing.plan_of(db, user, at=sub.period_end + timedelta(days=2)).key == "plus"
    assert billing.plan_of(db, user, at=sub.period_end + timedelta(days=4)).key == "free"


def test_webhook_ignores_unknown_payment_and_needs_secret(client, portone, monkeypatch):
    payload, headers = signed(paid_event("eu-not-ours"))
    assert client.post("/api/billing/webhook", content=payload, headers=headers).json()["result"] == "unknown"
    monkeypatch.setattr(get_settings(), "portone_webhook_secret", None)
    assert client.post("/api/billing/webhook", content=payload, headers=headers).status_code == 503


def test_plan_raises_daily_ai_limit(client, auth, portone, db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_daily_limit_usd", 0.5)
    monkeypatch.setattr(s, "ai_daily_limit_calls", 150)
    user = db.query(m.User).one()
    assert quota.limits(db, user) == (0.5, 150)
    subscribe(client, auth)
    assert quota.limits(db, user) == (3.0, 600)
    monkeypatch.setattr(s, "ai_daily_limit_calls", 0)  # 기본이 제한 없음이면 구독자도
    assert quota.limits(db, user)[1] == 0


def test_add_month_clamps_day():
    assert billing.add_month(datetime(2027, 1, 31, tzinfo=UTC)) == datetime(2027, 2, 28, tzinfo=UTC)
    assert billing.add_month(datetime(2026, 12, 15, tzinfo=UTC)) == datetime(2027, 1, 15, tzinfo=UTC)


def test_account_delete_revokes_and_deletes_billing_key(client, auth, portone):
    subscribe(client, auth)
    portone.calls.clear()
    email = client.get("/api/me", headers=auth).json()["email"]
    assert client.request("DELETE", "/api/me", headers=auth, json={"confirm_email": email}).status_code == 204
    assert ("revoke", "billing-key-1") in portone.calls and ("delete", "billing-key-1") in portone.calls
