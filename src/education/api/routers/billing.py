"""월 구독 결제 — 요금제·내 구독, 구독 시작, 해지·해지 취소, PortOne 웹훅 (services/billing.py)."""

import logging

from fastapi import APIRouter, HTTPException, Request
from portone_server_sdk import webhook as po_webhook
from pydantic import BaseModel, Field

from education.api.deps import DB, CurrentUser
from education.config import get_settings
from education.services import billing

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["결제"])


class SubscribeIn(BaseModel):
    plan: str = Field(max_length=16)
    billing_key: str = Field(min_length=8, max_length=200)


def _fail(e: billing.BillingError) -> HTTPException:
    return HTTPException(e.status, e.message)


@router.get("")
def my_billing(user: CurrentUser, db: DB) -> dict:
    return billing.status(db, user)


@router.post("/subscribe")
def subscribe(body: SubscribeIn, user: CurrentUser, db: DB) -> dict:
    try:
        billing.subscribe(db, user, body.plan, body.billing_key)
    except billing.BillingError as e:
        raise _fail(e) from e
    return billing.status(db, user)


@router.post("/cancel")
def cancel(user: CurrentUser, db: DB) -> dict:
    try:
        billing.cancel(db, user)
    except billing.BillingError as e:
        raise _fail(e) from e
    return billing.status(db, user)


@router.post("/resume")
def resume(user: CurrentUser, db: DB) -> dict:
    try:
        billing.resume(db, user)
    except billing.BillingError as e:
        raise _fail(e) from e
    return billing.status(db, user)


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: DB) -> dict:
    """PortOne 웹훅 — 서명을 확인하고, 내용은 믿지 않고 결제를 다시 조회해 반영한다"""
    secret = get_settings().portone_webhook_secret
    if not secret:
        raise HTTPException(503, "webhook not configured")
    payload = (await request.body()).decode("utf-8", "replace")
    try:
        event = po_webhook.verify(secret, payload, request.headers)
    except po_webhook.WebhookVerificationError as e:
        raise HTTPException(400, "invalid signature") from e
    data = getattr(event, "data", None)
    payment_id = getattr(data, "payment_id", None)
    if payment_id:
        try:
            result = billing.sync_payment(db, payment_id)
        except Exception:  # PortOne 이 다시 보내도록 500 — 재시도는 최대 5번
            log.exception("billing webhook: sync failed %s", payment_id)
            raise HTTPException(500, "sync failed") from None
        return {"ok": True, "result": result}
    return {"ok": True}
