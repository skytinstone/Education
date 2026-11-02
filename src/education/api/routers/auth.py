import secrets
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser
from education.api.dto import (
    AccountDeleteIn, ConnectionOut, ConnectionsOut, LinkStartOut, LoginIn, PasswordIn, SignupIn, SocialLinkIn, SocialSignupIn, TicketIn,
    TokenOut, UserOut, UserPatch,
)
from education.config import get_settings
from education.db import models as m
from education.security import create_ticket, create_token, hash_password, read_ticket, verify_password
from education.services import avatars, materials, oauth, schools
from education.services.oauth import OAuthError, Provider, SocialProfile

router = APIRouter(tags=["인증 · 사용자"])

LOGIN_PAGE = "/app/login.html"
SETTINGS_PAGE = "/app/index.html#/settings"
STATE_COOKIE = "eureka_oauth_state"
# 계정 설정에서 '연결하기'로 시작한 경우: 누가 시작했는지를 서명된 티켓으로 담아 둔다 (콜백은 브라우저 이동이라 로그인 토큰이 없다)
LINK_COOKIE = "eureka_oauth_link"
COOKIE_PATH = "/api/auth"


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
def _redirect(url: str) -> RedirectResponse:
    res = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    res.delete_cookie(STATE_COOKIE, path=COOKIE_PATH)
    res.delete_cookie(LINK_COOKIE, path=COOKIE_PATH)
    return res


def _to_login_page(**params: str) -> RedirectResponse:
    """결과를 로그인 화면의 주소 # 뒤에 담아 돌려보낸다 (# 뒤는 서버로 전송되지 않는다)."""
    return _redirect(f"{LOGIN_PAGE}#{urlencode(params)}")


def _to_settings(**params: str) -> RedirectResponse:
    """계정 설정에서 시작한 연결의 결과 — 설정 화면 주소의 ? 뒤에 담는다 (앱은 # 뒤를 경로로 쓴다)."""
    return _redirect(f"{SETTINGS_PAGE}?{urlencode(params)}")


def _set_cookie(res: Response, key: str, value: str) -> None:
    res.set_cookie(key, value, max_age=600, httponly=True, samesite="lax", path=COOKIE_PATH,
                   secure=get_settings().public_base_url.startswith("https"))


def _account(db: Session, provider: str, provider_user_id: str) -> m.OAuthAccount | None:
    return db.scalar(select(m.OAuthAccount).where(
        m.OAuthAccount.provider == provider, m.OAuthAccount.provider_user_id == provider_user_id))


def _connect(db: Session, user: m.User, provider: str, provider_user_id: str, email: str | None,
             email_verified: bool) -> None:
    """간편 로그인 계정을 user 에 붙인다. 제공자가 인증한 이메일이 계정 이메일과 같으면 계정 이메일도 인증된 것으로 본다."""
    db.add(m.OAuthAccount(user_id=user.id, provider=provider, provider_user_id=provider_user_id, email=email))
    if email_verified and email == user.email:
        user.email_verified = True
    db.commit()


def _find_user(db: Session, profile: SocialProfile) -> tuple[m.User | None, str]:
    """(사용자, 결과) — 결과: login(연결된 계정) · linked(같은 이메일 계정에 새로 연결) · new
    · email_taken(같은 이메일 계정이 있지만 자동 연결할 수 없음 — 그 계정을 함께 돌려준다)"""
    account = _account(db, profile.provider, profile.provider_user_id)
    if account:
        return db.get(m.User, account.user_id), "login"
    email = profile.email.lower() if profile.email else None
    existing = db.scalar(select(m.User).where(m.User.email == email)) if email else None
    if existing is None:
        return None, "new"
    # 양쪽 모두 이메일 주인이 확인된 경우에만 자동 연결 — 남의 이메일로 미리 가입해 둔 계정을 가로채는 것을 막는다
    if profile.email_verified and existing.email_verified:
        _connect(db, existing, profile.provider, profile.provider_user_id, email, True)
        return existing, "linked"
    return existing, "email_taken"


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
    _set_cookie(res, STATE_COOKIE, state)
    res.delete_cookie(LINK_COOKIE, path=COOKIE_PATH)  # 예전에 시작하다 만 '연결하기'가 이번 로그인에 섞이지 않게
    return res


def _link_callback(db: Session, provider: Provider, user_id: UUID, profile: SocialProfile) -> RedirectResponse:
    """계정 설정에서 시작한 연결: 로그인한 사용자에게 이 간편 로그인 계정을 붙인다."""
    user = db.get(m.User, user_id)
    if user is None:
        return _to_login_page(error="state", provider=provider)
    account = _account(db, provider, profile.provider_user_id)
    if account:
        return _to_settings(linked=provider) if account.user_id == user.id else _to_settings(link_error="taken", provider=provider)
    if db.scalar(select(m.OAuthAccount.id).where(m.OAuthAccount.user_id == user.id, m.OAuthAccount.provider == provider)):
        return _to_settings(link_error="duplicate", provider=provider)  # 다른 Google 계정이 이미 연결돼 있음
    email = profile.email.lower() if profile.email else None
    _connect(db, user, provider, profile.provider_user_id, email, profile.email_verified)
    return _to_settings(linked=provider)


@router.get("/auth/{provider}/callback", include_in_schema=False)
def social_callback(provider: Provider, request: Request, db: DB, code: str | None = None,
                    state: str | None = None, error: str | None = None) -> RedirectResponse:
    link = read_ticket(request.cookies.get(LINK_COOKIE, ""), "link_start")
    fail = (lambda e: _to_settings(link_error=e, provider=provider)) if link else (lambda e: _to_login_page(error=e, provider=provider))
    if error:  # 사용자가 동의 화면에서 취소
        return fail("cancelled")
    expected = request.cookies.get(STATE_COOKIE)
    if not (code and state and expected and secrets.compare_digest(state, expected)):
        return _to_login_page(error="state", provider=provider)
    if link and link.get("state") != state:
        return _to_login_page(error="state", provider=provider)
    if oauth.client_credentials(provider) is None:
        return fail("not_configured")
    try:
        profile = oauth.fetch_profile(provider, code)
    except OAuthError:
        return fail("provider")
    if link:
        return _link_callback(db, provider, UUID(link["sub"]), profile)

    user, outcome = _find_user(db, profile)
    if outcome == "email_taken":
        if user.password_hash is None:  # 다른 간편 로그인으로만 가입한 계정 — 그쪽으로 로그인한 뒤 설정에서 연결
            via = db.scalars(select(m.OAuthAccount.provider).where(m.OAuthAccount.user_id == user.id))
            return _to_login_page(error="email_taken_social", provider=provider, via=",".join(sorted(set(via))))
        # 이메일로 가입한 계정 — 그 계정의 비밀번호를 한 번 확인하고 연결한다 (프로필은 서명된 티켓에 담아 둔다)
        ticket = create_ticket("link", {"sub": str(user.id), "provider": provider, "pid": profile.provider_user_id,
                                        "email": user.email, "ev": profile.email_verified}, timedelta(minutes=10))
        return _to_login_page(social_link=ticket, provider=provider, email=user.email)
    if user:
        return _to_login_page(login_ticket=create_ticket("login", {"sub": str(user.id)}, timedelta(minutes=2)))
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


@router.post("/auth/social/link")
def social_link(body: SocialLinkIn, db: DB) -> TokenOut:
    """같은 이메일로 이미 가입한 계정에 간편 로그인을 연결한다 — 그 계정의 비밀번호로 본인 확인."""
    c = read_ticket(body.link_token, "link")
    user = db.get(m.User, UUID(c["sub"])) if c else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "연결 시간이 지났어요. 간편 로그인을 다시 시도해 주세요")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "비밀번호가 맞지 않아요")
    account = _account(db, c["provider"], c["pid"])
    if account and account.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "이 간편 로그인 계정은 이미 다른 Eureka 계정에 연결돼 있어요")
    if account is None:
        try:
            _connect(db, user, c["provider"], c["pid"], c["email"], c["ev"])
        except IntegrityError:  # 버튼을 두 번 누른 경우 등
            db.rollback()
            if _account(db, c["provider"], c["pid"]) is None:
                raise
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


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(body: AccountDeleteIn, user: CurrentUser, db: DB) -> Response:
    """회원 탈퇴 — 계정과 학습 기록(DB 에서 함께 지워짐), 올린 기출 파일, 프로필 사진을 지운다.
    백업에는 최대 90일 남았다가 자동 삭제된다 (개인정보처리방침 4번)."""
    if body.confirm_email.strip().lower() != user.email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "이메일이 맞지 않아요")
    user_id = user.id
    db.delete(user)  # 학습 기록·프로젝트·카드 등은 DB 의 ON DELETE CASCADE 로 함께 지워진다
    db.commit()
    avatars.delete_photo(user_id)
    materials.delete_user_files(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 로그인 방법 (계정 설정) ----------
def _connections(db: Session, user: m.User) -> ConnectionsOut:
    rows = db.scalars(select(m.OAuthAccount).where(m.OAuthAccount.user_id == user.id).order_by(m.OAuthAccount.created_at))
    return ConnectionsOut(has_password=user.password_hash is not None,
                          accounts=[ConnectionOut.model_validate(a) for a in rows], available=providers())


@router.get("/me/connections")
def list_connections(user: CurrentUser, db: DB) -> ConnectionsOut:
    return _connections(db, user)


@router.post("/me/connections/{provider}/start")
def start_connection(provider: Provider, user: CurrentUser, response: Response) -> LinkStartOut:
    """연결 시작 — 화면은 돌려받은 url 로 이동한다. 콜백이 누구에게 붙일지 알 수 있게 서명된 쿠키를 함께 심는다."""
    if oauth.client_credentials(provider) is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "이 간편 로그인은 아직 준비 중이에요")
    state = secrets.token_urlsafe(32)
    _set_cookie(response, STATE_COOKIE, state)
    _set_cookie(response, LINK_COOKIE, create_ticket("link_start", {"sub": str(user.id), "state": state}, timedelta(minutes=10)))
    return LinkStartOut(url=oauth.authorize_url(provider, state))


@router.delete("/me/connections/{provider}")
def remove_connection(provider: Provider, user: CurrentUser, db: DB) -> ConnectionsOut:
    count = db.scalar(select(func.count()).where(m.OAuthAccount.user_id == user.id))
    if user.password_hash is None and count <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "로그인 방법이 하나뿐이라 해제할 수 없어요. 비밀번호를 먼저 만들어 주세요")
    db.execute(delete(m.OAuthAccount).where(m.OAuthAccount.user_id == user.id, m.OAuthAccount.provider == provider))
    db.commit()
    return _connections(db, user)


@router.put("/me/password")
def set_password(body: PasswordIn, user: CurrentUser, db: DB) -> ConnectionsOut:
    """간편 로그인으로만 가입했으면 새로 만들고, 이미 있으면 현재 비밀번호를 확인하고 바꾼다."""
    if user.password_hash is not None and not verify_password(body.current_password or "", user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "현재 비밀번호가 맞지 않아요")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return _connections(db, user)


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


@router.get("/search/schools", tags=["인증 · 사용자"])
def search_schools(q: str, user: CurrentUser) -> list[schools.School]:
    """계정 설정의 학교 검색 (초·중·고, 나이스). 두 글자 이상."""
    q = q.strip()
    if len(q) < 2:
        return []
    try:
        return list(schools.search(q[:30]))
    except schools.SchoolSearchError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "학교 검색이 잠시 안 돼요. 직접 입력해 주세요") from None


@router.get("/users/{user_id}/avatar", include_in_schema=False)
def get_avatar(user_id: UUID, db: DB) -> FileResponse:
    """<img> 로 불러오므로 로그인 없이 열린다 (주소에 추측할 수 없는 사용자 id 가 들어감)."""
    user = db.get(m.User, user_id)
    path = avatars.path_for(user_id)
    if user is None or user.avatar_type != "photo" or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사진이 없어요")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})
