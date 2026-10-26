"""간편 로그인 — 실제 Google·카카오 대신 프로필 응답을 흉내 내서 흐름 전체를 검증한다."""

from urllib.parse import parse_qs, urlparse

import pytest

from education.config import get_settings
from education.db import models as m
from education.services import oauth
from education.services.oauth import SocialProfile, parse_profile

CONSENT = {"over_14": True, "agreed_terms": True}


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    for k, v in {"google_client_id": "gid", "google_client_secret": "gsecret",
                 "kakao_rest_api_key": "kid", "kakao_client_secret": None,
                 "public_base_url": "http://localhost:8000"}.items():
        monkeypatch.setattr(s, k, v)


@pytest.fixture
def profile(monkeypatch):
    """다음 콜백에서 제공자가 돌려줄 프로필을 정한다."""
    box = {}
    monkeypatch.setattr(oauth, "fetch_profile", lambda provider, code: box["p"])
    return lambda **kw: box.__setitem__("p", SocialProfile(**kw))


def fragment(res) -> dict:
    assert res.status_code == 302, res.text
    loc = urlparse(res.headers["location"])
    assert loc.path == "/app/login.html"
    return {k: v[0] for k, v in parse_qs(loc.fragment, keep_blank_values=True).items()}


def login_via(client, provider: str) -> dict:
    start = client.get(f"/api/auth/{provider}/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return fragment(client.get(f"/api/auth/{provider}/callback?code=abc&state={state}", follow_redirects=False))


def test_providers_and_not_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", None)
    monkeypatch.setattr(get_settings(), "kakao_rest_api_key", None)
    assert client.get("/api/auth/providers").json() == {"google": False, "kakao": False}
    assert fragment(client.get("/api/auth/google/start", follow_redirects=False))["error"] == "not_configured"


def test_start_redirects_with_state_cookie(client, configured):
    assert client.get("/api/auth/providers").json() == {"google": True, "kakao": True}
    res = client.get("/api/auth/google/start", follow_redirects=False)
    url = urlparse(res.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["client_id"] == ["gid"] and q["redirect_uri"] == ["http://localhost:8000/api/auth/google/callback"]
    assert "email" in q["scope"][0]
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and q["state"][0] in cookie and "Path=/api/auth" in cookie
    assert "kauth.kakao.com" in client.get("/api/auth/kakao/start", follow_redirects=False).headers["location"]


def test_callback_rejects_bad_state_and_cancel(client, configured, profile):
    client.get("/api/auth/google/start", follow_redirects=False)
    assert fragment(client.get("/api/auth/google/callback?code=abc&state=forged", follow_redirects=False))["error"] == "state"
    client.cookies.clear()
    assert fragment(client.get("/api/auth/google/callback?code=abc&state=x", follow_redirects=False))["error"] == "state"
    assert fragment(client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False))["error"] == "cancelled"


def test_new_google_user_signs_up_once_then_logs_in(client, configured, profile, db):
    profile(provider="google", provider_user_id="g-1", email="New@Gmail.com", email_verified=True, name="민석")
    f = login_via(client, "google")
    assert f["name"] == "민석" and f["email"] == "new@gmail.com" and "social_signup" in f

    no_consent = client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], "over_14": False, "agreed_terms": True})
    assert no_consent.status_code == 422
    r = client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], **CONSENT})
    assert r.status_code == 201 and r.json()["user"]["email"] == "new@gmail.com"
    user = db.get(m.User, r.json()["user"]["id"])
    assert user.email_verified and user.password_hash is None

    # 두 번째부터는 약관 없이 바로 로그인
    f = login_via(client, "google")
    assert "login_ticket" in f and "social_signup" not in f
    token = client.post("/api/auth/social/exchange", json={"ticket": f["login_ticket"]}).json()["access_token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()["id"] == str(user.id)


def test_kakao_without_email_asks_for_it(client, configured, profile, db):
    profile(provider="kakao", provider_user_id="12345", email=None, email_verified=False, name="카카오친구")
    f = login_via(client, "kakao")
    assert f["email"] == ""
    assert client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], **CONSENT}).status_code == 422
    r = client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], "email": "me@example.com", **CONSENT})
    assert r.status_code == 201
    assert db.get(m.User, r.json()["user"]["id"]).email_verified is False  # 직접 입력한 이메일은 미인증


def test_verified_emails_link_accounts(client, configured, profile):
    profile(provider="google", provider_user_id="g-2", email="same@gmail.com", email_verified=True, name="A")
    f = login_via(client, "google")
    uid = client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], **CONSENT}).json()["user"]["id"]

    profile(provider="kakao", provider_user_id="777", email="same@gmail.com", email_verified=True, name="A")
    f = login_via(client, "kakao")
    assert "login_ticket" in f  # 같은 인증 이메일 → 기존 계정에 카카오 연결
    assert client.post("/api/auth/social/exchange", json={"ticket": f["login_ticket"]}).json()["user"]["id"] == uid


def test_unverified_existing_account_is_not_linked(client, configured, profile, new_user):
    new_user(email="victim@gmail.com")  # 이메일 인증 없이 가입된 계정
    profile(provider="google", provider_user_id="g-3", email="victim@gmail.com", email_verified=True, name="V")
    assert login_via(client, "google")["error"] == "email_taken"


def test_tickets_are_not_interchangeable(client, configured, profile, auth):
    profile(provider="google", provider_user_id="g-4", email="t@gmail.com", email_verified=True, name="T")
    f = login_via(client, "google")
    access = client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], **CONSENT}).json()["access_token"]
    ticket = login_via(client, "google")["login_ticket"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401  # 티켓으로 API 호출 불가
    assert client.post("/api/auth/social/exchange", json={"ticket": access}).status_code == 401  # 로그인 토큰을 티켓으로 못 씀
    assert client.post("/api/auth/social/complete", json={"signup_token": ticket, **CONSENT}).status_code == 401


def test_double_submit_returns_same_account(client, configured, profile):
    profile(provider="google", provider_user_id="g-5", email="d@gmail.com", email_verified=True, name="D")
    token = login_via(client, "google")["social_signup"]
    a = client.post("/api/auth/social/complete", json={"signup_token": token, **CONSENT}).json()["user"]["id"]
    b = client.post("/api/auth/social/complete", json={"signup_token": token, **CONSENT}).json()["user"]["id"]
    assert a == b


def test_parse_provider_payloads():
    g = parse_profile("google", {"sub": "1", "email": "A@Gmail.com", "email_verified": True, "name": "가"})
    assert (g.provider_user_id, g.email, g.email_verified, g.name) == ("1", "a@gmail.com", True, "가")
    k = parse_profile("kakao", {"id": 99, "kakao_account": {"email": "k@kakao.com", "is_email_valid": True,
                                                            "is_email_verified": False, "profile": {"nickname": "나"}}})
    assert (k.provider_user_id, k.email, k.email_verified, k.name) == ("99", "k@kakao.com", False, "나")
    bare = parse_profile("kakao", {"id": 5})
    assert bare.email is None and bare.name is None
