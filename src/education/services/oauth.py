"""Google · 카카오 간편 로그인 (OAuth 2.0 인가 코드 방식).

흐름: 로그인 시작 → 제공자 로그인·동의 화면 → 콜백으로 code 수신 → code 를 토큰으로 교환 → 프로필 조회.
여기서는 제공자와의 통신만 하고, 계정 생성·연결은 api/routers/auth.py 가 맡는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

import httpx2

from education.config import get_settings

Provider = Literal["google", "kakao"]


@dataclass(frozen=True)
class SocialProfile:
    provider: Provider
    provider_user_id: str
    email: str | None
    email_verified: bool  # 제공자가 이메일 주인임을 확인했는지
    name: str | None


class OAuthError(Exception):
    pass


ENDPOINTS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "profile": "https://openidconnect.googleapis.com/v1/userinfo",
    },
    "kakao": {
        "authorize": "https://kauth.kakao.com/oauth/authorize",
        "token": "https://kauth.kakao.com/oauth/token",
        "profile": "https://kapi.kakao.com/v2/user/me",
    },
}


def client_credentials(provider: Provider) -> tuple[str, str | None] | None:
    """(client_id, client_secret). 설정되지 않았으면 None."""
    s = get_settings()
    if provider == "google":
        return (s.google_client_id, s.google_client_secret) if s.google_client_id and s.google_client_secret else None
    return (s.kakao_rest_api_key, s.kakao_client_secret) if s.kakao_rest_api_key else None  # 카카오 secret 은 선택


def redirect_uri(provider: Provider) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/auth/{provider}/callback"


def authorize_url(provider: Provider, state: str) -> str:
    client_id, _ = client_credentials(provider)
    params = {"client_id": client_id, "redirect_uri": redirect_uri(provider), "response_type": "code", "state": state}
    if provider == "google":
        params |= {"scope": "openid email profile", "prompt": "select_account"}
    # 카카오는 콘솔의 '동의항목' 설정을 따른다 (scope 를 따로 요청하면 설정과 다를 때 오류가 난다)
    return f"{ENDPOINTS[provider]['authorize']}?{urlencode(params)}"


def fetch_profile(provider: Provider, code: str) -> SocialProfile:
    client_id, secret = client_credentials(provider)
    form = {"grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect_uri(provider), "code": code}
    if secret:
        form["client_secret"] = secret
    try:
        with httpx2.Client(timeout=10) as http:
            token = http.post(ENDPOINTS[provider]["token"], data=form)
            token.raise_for_status()
            access_token = token.json()["access_token"]
            res = http.get(ENDPOINTS[provider]["profile"], headers={"Authorization": f"Bearer {access_token}"})
            res.raise_for_status()
            data = res.json()
    except (httpx2.HTTPError, KeyError, ValueError) as e:
        raise OAuthError(f"{provider} 로그인 처리 실패: {e}") from e
    return parse_profile(provider, data)


def parse_profile(provider: Provider, data: dict) -> SocialProfile:
    if provider == "google":
        return SocialProfile(
            provider="google", provider_user_id=str(data["sub"]),
            email=(data.get("email") or "").lower() or None,
            email_verified=bool(data.get("email_verified")), name=data.get("name"),
        )
    account = data.get("kakao_account") or {}
    return SocialProfile(
        provider="kakao", provider_user_id=str(data["id"]),
        email=(account.get("email") or "").lower() or None,
        # 카카오: 유효하고(is_email_valid) 인증된(is_email_verified) 이메일만 인증된 것으로 본다
        email_verified=bool(account.get("is_email_valid") and account.get("is_email_verified")),
        name=(account.get("profile") or {}).get("nickname"),
    )
