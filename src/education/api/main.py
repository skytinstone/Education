"""Eureka API 서버.

    uv run uvicorn education.api.main:app --reload
    → API 문서  http://127.0.0.1:8000/docs
    → 프로토타입 http://127.0.0.1:8000/app/login.html
"""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from education.api.deps import DB
from education.api.routers import auth, learning, projects, sessions, sync
from education.config import ROOT, get_settings

app = FastAPI(title="Eureka API", version="0.1.0", description="Horcrux Technologies · Eureka — 시험 준비 AI 학습 에이전트")
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False,
    allow_methods=["*"], allow_headers=["Authorization", "Content-Type"],
)

api = APIRouter(prefix="/api")
for r in (auth.router, projects.router, projects.material_router, sessions.router, learning.router, sync.router):
    api.include_router(r)


@api.get("/health", tags=["상태"])
def health(db: DB) -> dict:
    db.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(api)
# 프로토타입 화면을 같은 서버(같은 출처)로 서빙 — CORS 없이 API 를 부를 수 있다
app.mount("/app", StaticFiles(directory=ROOT / "prototype", html=True), name="app")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/login.html")
