"""간편 로그인 — 실제 Google·카카오 대신 프로필 응답을 흉내 내서 흐름 전체를 검증한다."""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

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


def test_unverified_existing_account_needs_password_to_link(client, configured, profile, new_user, db):
    new_user(email="victim@gmail.com")  # 이메일 인증 없이 가입된 계정
    profile(provider="google", provider_user_id="g-3", email="victim@gmail.com", email_verified=True, name="V")
    f = login_via(client, "google")
    assert "login_ticket" not in f and f["email"] == "victim@gmail.com"  # 자동 연결하지 않고 비밀번호 확인으로

    wrong = client.post("/api/auth/social/link", json={"link_token": f["social_link"], "password": "nope1234"})
    assert wrong.status_code == 403
    assert db.scalar(select(func.count()).select_from(m.OAuthAccount).where(m.OAuthAccount.provider_user_id == "g-3")) == 0

    r = client.post("/api/auth/social/link", json={"link_token": f["social_link"], "password": "abc12345"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "victim@gmail.com"
    user = db.get(m.User, r.json()["user"]["id"])
    db.refresh(user)
    assert user.email_verified  # Google 이 인증한 이메일 + 비밀번호 확인 → 이 이메일의 주인
    again = client.post("/api/auth/social/link", json={"link_token": f["social_link"], "password": "abc12345"})
    assert again.status_code == 200  # 두 번 눌러도 같은 계정

    # 이제 Google 로 바로 로그인되고, 이메일이 인증됐으니 카카오(인증 이메일)는 자동 연결된다
    assert "login_ticket" in login_via(client, "google")
    profile(provider="kakao", provider_user_id="k-3", email="victim@gmail.com", email_verified=True, name="V")
    assert "login_ticket" in login_via(client, "kakao")


def test_link_ticket_is_its_own_kind(client, configured, profile, new_user):
    new_user(email="lk@gmail.com")
    profile(provider="google", provider_user_id="g-6", email="lk@gmail.com", email_verified=True, name="L")
    link = login_via(client, "google")["social_link"]
    assert client.post("/api/auth/social/exchange", json={"ticket": link}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": f"Bearer {link}"}).status_code == 401
    assert client.post("/api/auth/social/link", json={"link_token": "forged", "password": "abc12345"}).status_code == 401


def test_social_only_account_points_to_its_provider(client, configured, profile):
    # 카카오에서 이메일을 못 받아 직접 입력한(미인증) 계정 — 비밀번호가 없으니 카카오로 로그인 후 설정에서 연결
    profile(provider="kakao", provider_user_id="k-7", email=None, email_verified=False, name="K")
    f = login_via(client, "kakao")
    client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], "email": "so@gmail.com", **CONSENT})
    profile(provider="google", provider_user_id="g-7", email="so@gmail.com", email_verified=True, name="K")
    f = login_via(client, "google")
    assert f["error"] == "email_taken_social" and f["via"] == "kakao"


# ---------- 계정 설정에서 연결 · 해제 ----------
def connect_via(client, headers, provider: str):
    start = client.post(f"/api/me/connections/{provider}/start", headers=headers)
    assert start.status_code == 200, start.text
    state = parse_qs(urlparse(start.json()["url"]).query)["state"][0]
    res = client.get(f"/api/auth/{provider}/callback?code=abc&state={state}", follow_redirects=False)
    assert res.status_code == 302
    loc = urlparse(res.headers["location"])
    assert loc.path == "/app/index.html"
    path, _, qs = loc.fragment.partition("?")
    assert path == "/settings"
    return {k: v[0] for k, v in parse_qs(qs).items()}


def test_connect_and_disconnect_from_settings(client, configured, profile, auth, new_user):
    assert client.get("/api/me/connections", headers=auth).json()["accounts"] == []
    profile(provider="google", provider_user_id="g-8", email="other@gmail.com", email_verified=True, name="S")
    assert connect_via(client, auth, "google") == {"linked": "google"}
    c = client.get("/api/me/connections", headers=auth).json()
    assert c["has_password"] and [a["provider"] for a in c["accounts"]] == ["google"]
    assert connect_via(client, auth, "google") == {"linked": "google"}  # 이미 연결된 같은 계정은 그대로

    # 연결한 Google 로 바로 로그인된다 (이메일이 달라도)
    assert "login_ticket" in login_via(client, "google")

    # 다른 사용자가 같은 Google 계정을 연결하려 하면 막는다
    other = new_user()
    assert connect_via(client, other, "google") == {"link_error": "taken", "provider": "google"}
    # 이미 Google 이 있는 사용자가 다른 Google 계정을 또 붙이려 하면 막는다
    profile(provider="google", provider_user_id="g-9", email="x@gmail.com", email_verified=True, name="S")
    assert connect_via(client, auth, "google") == {"link_error": "duplicate", "provider": "google"}

    r = client.delete("/api/me/connections/google", headers=auth)
    assert r.status_code == 200 and r.json()["accounts"] == []


def test_link_cookie_does_not_leak_into_next_login(client, configured, profile, auth):
    client.post("/api/me/connections/google/start", headers=auth)  # 시작만 하고 그만둠
    profile(provider="google", provider_user_id="g-10", email="fresh@gmail.com", email_verified=True, name="F")
    f = login_via(client, "google")  # 일반 로그인 시작은 연결 쿠키를 지운다
    assert "social_signup" in f


def test_cannot_remove_last_login_method_until_password_set(client, configured, profile):
    profile(provider="google", provider_user_id="g-11", email="only@gmail.com", email_verified=True, name="O")
    f = login_via(client, "google")
    token = client.post("/api/auth/social/complete", json={"signup_token": f["social_signup"], **CONSENT}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.delete("/api/me/connections/google", headers=h).status_code == 409

    assert client.put("/api/me/password", headers=h, json={"new_password": "short"}).status_code == 422
    r = client.put("/api/me/password", headers=h, json={"new_password": "newpass123"})
    assert r.status_code == 200 and r.json()["has_password"]
    assert client.post("/api/auth/login", json={"email": "only@gmail.com", "password": "newpass123"}).status_code == 200
    # 비밀번호가 생긴 뒤에는 바꿀 때 현재 비밀번호가 필요하다
    assert client.put("/api/me/password", headers=h, json={"new_password": "another123"}).status_code == 403
    assert client.put("/api/me/password", headers=h, json={"current_password": "newpass123", "new_password": "another123"}).status_code == 200
    assert client.delete("/api/me/connections/google", headers=h).status_code == 200


def test_settings_link_cancel_returns_to_settings(client, configured, auth):
    client.post("/api/me/connections/kakao/start", headers=auth)
    res = client.get("/api/auth/kakao/callback?error=access_denied", follow_redirects=False)
    assert res.headers["location"].startswith("/app/index.html#/settings?link_error=cancelled")


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
