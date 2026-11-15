"""Eureka API 서버.

    uv run uvicorn education.api.main:app --reload
    → API 문서  http://127.0.0.1:8000/docs
    → 소개 페이지 http://127.0.0.1:8000/
    → 관리자 페이지 http://127.0.0.1:8000/admin
    → 프로토타입 http://127.0.0.1:8000/app/login.html
"""

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from education.api.deps import DB
from education.api.routers import admin, auth, books, courses, feedback, learning, notifications, projects, sessions, sync, visits
from education.config import ROOT, get_settings

# 오류 추적 (Sentry) — .env 에 SENTRY_DSN 이 있을 때만. 개인정보(요청 본문·쿠키 등)는 보내지 않는다
if get_settings().sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=get_settings().sentry_dsn, environment=get_settings().sentry_environment,
                    send_default_pii=False, traces_sample_rate=0.0)

app = FastAPI(title="Eureka API", version="0.1.0", description="Horcrux Technologies · Eureka — 시험 준비 AI 학습 에이전트")
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False,
    allow_methods=["*"], allow_headers=["Authorization", "Content-Type"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """모든 응답에 기본 보안 헤더 (다른 사이트가 화면을 몰래 감싸기·형식 추측 등 방지, 마이크는 이 사이트에서만)."""
    res = await call_next(request)
    h = res.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=(), payment=()")
    if request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return res


api = APIRouter(prefix="/api")
for r in (auth.router, projects.router, projects.material_router, sessions.router, learning.router, sync.router,
          feedback.router, feedback.admin, admin.router, notifications.router, courses.router, books.router,
          visits.router):
    api.include_router(r)


@api.get("/health", tags=["상태"])
def health(db: DB) -> dict:
    db.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(api)
# 프로토타입 화면을 같은 서버(같은 출처)로 서빙 — CORS 없이 API 를 부를 수 있다
app.mount("/app", StaticFiles(directory=ROOT / "prototype", html=True), name="app")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """서비스 소개(랜딩) 페이지. 로그인·앱 화면은 /app/ 아래에 있다."""
    return FileResponse(ROOT / "prototype" / "landing.html")


@app.get("/robots.txt", include_in_schema=False)
def robots() -> PlainTextResponse:
    base = get_settings().public_base_url.rstrip("/")
    lines = ["User-agent: *", "Allow: /$", "Allow: /app/terms.html", "Allow: /app/privacy.html",
             "Disallow: /app/", "Disallow: /admin", "Disallow: /api/", f"Sitemap: {base}/sitemap.xml"]
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> Response:
    base = get_settings().public_base_url.rstrip("/")
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/", "/app/login.html", "/app/terms.html", "/app/privacy.html"))
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                    media_type="application/xml")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    """관리자 페이지. 화면은 누구나 받지만, 데이터(/api/admin/*)는 ADMIN_EMAILS 계정에만 나간다."""
    return FileResponse(ROOT / "prototype" / "admin.html", headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"})
