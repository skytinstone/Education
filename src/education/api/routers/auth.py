import secrets
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser
from education.api.dto import LoginIn, SignupIn, SocialSignupIn, TicketIn, TokenOut, UserOut, UserPatch
from education.config import get_settings
from education.db import models as m
from education.security import create_ticket, create_token, hash_password, read_ticket, verify_password
from education.services import avatars, oauth
from education.services.oauth import OAuthError, Provider, SocialProfile

router = APIRouter(tags=["인증 · 사용자"])

LOGIN_PAGE = "/app/login.html"
STATE_COOKIE = "eureka_oauth_state"


def _token(user: m.User) -> TokenOut:
    return TokenOut(access_token=create_token(user.id), user=UserOut.model_validate(user))


# ---------- 이메일 가입 · 로그인 ----------
@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, db: DB) -> TokenOut:
    email = body.email.lower()
    if db.scalar(select(m.User.id).where(m.User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일이에요")
    user = m.User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
                  agreed_marketing=body.agreed_marketing)
    db.add(user)
    db.commit()
    return _token(user)


@router.post("/auth/login")
def login(body: LoginIn, db: DB) -> TokenOut:
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    # 이메일이 없는 경우와 비밀번호가 틀린 경우를 구분하지 않는다 (계정 존재 여부 노출 방지)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호를 확인해 주세요")
    return _token(user)


# ---------- 간편 로그인 (Google · 카카오) ----------
def _to_login_page(**params: str) -> RedirectResponse:
    """결과를 로그인 화면의 주소 # 뒤에 담아 돌려보낸다 (# 뒤는 서버로 전송되지 않는다)."""
    res = RedirectResponse(f"{LOGIN_PAGE}#{urlencode(params)}", status_code=status.HTTP_302_FOUND)
    res.delete_cookie(STATE_COOKIE, path="/api/auth")
    return res


def _find_user(db: Session, profile: SocialProfile) -> tuple[m.User | None, str]:
    """(사용자, 결과) — 결과: login(연결된 계정) · linked(같은 이메일 계정에 새로 연결) · email_taken · new"""
    account = db.scalar(select(m.OAuthAccount).where(
        m.OAuthAccount.provider == profile.provider, m.OAuthAccount.provider_user_id == profile.provider_user_id))
    if account:
        return db.get(m.User, account.user_id), "login"
    email = profile.email.lower() if profile.email else None
    existing = db.scalar(select(m.User).where(m.User.email == email)) if email else None
    if existing is None:
        return None, "new"
    # 양쪽 모두 이메일 주인이 확인된 경우에만 자동 연결 — 남의 이메일로 미리 가입해 둔 계정을 가로채는 것을 막는다
    if profile.email_verified and existing.email_verified:
        db.add(m.OAuthAccount(user_id=existing.id, provider=profile.provider,
                              provider_user_id=profile.provider_user_id, email=email))
        db.commit()
        return existing, "linked"
    return None, "email_taken"


@router.get("/auth/providers")
def providers() -> dict[str, bool]:
    """설정된 간편 로그인 — 화면에서 버튼을 켜고 끄는 데 쓴다."""
    return {p: oauth.client_credentials(p) is not None for p in ("google", "kakao")}


@router.get("/auth/{provider}/start", include_in_schema=False)
def social_start(provider: Provider) -> RedirectResponse:
    if oauth.client_credentials(provider) is None:
        return _to_login_page(error="not_configured", provider=provider)
    state = secrets.token_urlsafe(32)  # 다른 사이트가 로그인 과정을 위조하지 못하게 (CSRF)
    res = RedirectResponse(oauth.authorize_url(provider, state), status_code=status.HTTP_302_FOUND)
    res.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", path="/api/auth",
                   secure=get_settings().public_base_url.startswith("https"))
    return res


@router.get("/auth/{provider}/callback", include_in_schema=False)
def social_callback(provider: Provider, request: Request, db: DB, code: str | None = None,
                    state: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:  # 사용자가 동의 화면에서 취소
        return _to_login_page(error="cancelled", provider=provider)
    expected = request.cookies.get(STATE_COOKIE)
    if not (code and state and expected and secrets.compare_digest(state, expected)):
        return _to_login_page(error="state", provider=provider)
    if oauth.client_credentials(provider) is None:
        return _to_login_page(error="not_configured", provider=provider)
    try:
        profile = oauth.fetch_profile(provider, code)
    except OAuthError:
        return _to_login_page(error="provider", provider=provider)

    user, outcome = _find_user(db, profile)
    if user:
        return _to_login_page(login_ticket=create_ticket("login", {"sub": str(user.id)}, timedelta(minutes=2)))
    if outcome == "email_taken":
        return _to_login_page(error="email_taken", provider=provider)
    # 처음 온 사용자 → 약관 동의 화면으로 (프로필은 서명된 티켓에 담아 둔다)
    email = profile.email.lower() if profile.email else None
    ticket = create_ticket("signup", {"provider": profile.provider, "pid": profile.provider_user_id, "email": email,
                                      "ev": profile.email_verified, "name": profile.name}, timedelta(minutes=15))
    return _to_login_page(social_signup=ticket, provider=provider, name=profile.name or "", email=email or "")


@router.post("/auth/social/exchange")
def social_exchange(body: TicketIn, db: DB) -> TokenOut:
    """간편 로그인 직후 받은 짧은 티켓을 로그인 토큰으로 바꾼다."""
    claims = read_ticket(body.ticket, "login")
    user = db.get(m.User, UUID(claims["sub"])) if claims else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인 시간이 지났어요. 다시 시도해 주세요")
    return _token(user)


@router.post("/auth/social/complete", status_code=status.HTTP_201_CREATED)
def social_complete(body: SocialSignupIn, db: DB) -> TokenOut:
    """처음 온 간편 로그인 사용자의 약관 동의를 받고 계정을 만든다."""
    c = read_ticket(body.signup_token, "signup")
    if c is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "가입 시간이 지났어요. 다시 시도해 주세요")
    linked = db.scalar(select(m.OAuthAccount.user_id).where(
        m.OAuthAccount.provider == c["provider"], m.OAuthAccount.provider_user_id == c["pid"]))
    if linked:  # 가입 버튼을 두 번 누른 경우 등 — 이미 만들어진 계정으로 로그인
        return _token(db.get(m.User, linked))

    # 제공자가 준 이메일이 있으면 그것을, 없으면(카카오 이메일 미동의) 사용자가 입력한 것을 쓴다
    email = (c["email"] or body.email or "").lower() or None
    if not email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "이메일을 입력해 주세요")
    if db.scalar(select(m.User.id).where(m.User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일이에요. 처음 가입한 방법으로 로그인해 주세요")

    user = m.User(email=email, email_verified=bool(c["email"] and c["ev"]),
                  name=(c["name"] or email.split("@")[0])[:40], agreed_marketing=body.agreed_marketing)
    db.add(user)
    try:
        db.flush()
        db.add(m.OAuthAccount(user_id=user.id, provider=c["provider"], provider_user_id=c["pid"], email=c["email"]))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 처리된 가입이에요. 다시 로그인해 주세요") from None
    return _token(user)


# ---------- 내 정보 ----------
@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me")
def update_me(body: UserPatch, user: CurrentUser, db: DB) -> UserOut:
    changes = body.model_dump(exclude_unset=True)
    for k in ("name", "daily_goal"):
        if changes.get(k) is not None:
            setattr(user, k, changes[k].strip() if isinstance(changes[k], str) else changes[k])
    for k in ("birth_date", "school", "major", "address"):  # 선택 항목: 빈 값이면 지운다
        if k in changes:
            v = changes[k]
            setattr(user, k, (v.strip() or None) if isinstance(v, str) else v)
    if "avatar" in changes:
        avatar = changes["avatar"]
        if avatar == "initial":
            avatars.delete_photo(user.id)
            user.avatar_type, user.avatar_preset = "initial", None
        elif avatar in avatars.PRESETS:
            avatars.delete_photo(user.id)
            user.avatar_type, user.avatar_preset = "preset", avatar
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "없는 캐릭터예요")
    db.commit()
    return UserOut.model_validate(user)


@router.post("/me/avatar")
def upload_avatar(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()]) -> UserOut:
    """프로필 사진 — 256px 정사각형으로 다시 만들어 저장 (위치 정보 등 메타데이터 제거)."""
    try:
        avatars.save_photo(user.id, file.file.read(avatars.MAX_BYTES + 1))
    except avatars.AvatarError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    user.avatar_type, user.avatar_preset = "photo", None
    user.avatar_version += 1
    db.commit()
    return UserOut.model_validate(user)


@router.get("/users/{user_id}/avatar", include_in_schema=False)
def get_avatar(user_id: UUID, db: DB) -> FileResponse:
    """<img> 로 불러오므로 로그인 없이 열린다 (주소에 추측할 수 없는 사용자 id 가 들어감)."""
    user = db.get(m.User, user_id)
    path = avatars.path_for(user_id)
    if user is None or user.avatar_type != "photo" or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사진이 없어요")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})
