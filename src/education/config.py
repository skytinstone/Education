"""환경 설정 — .env 또는 환경 변수에서 읽는다 (.env.example 참고)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str
    test_database_url: str | None = None
    jwt_secret: str
    jwt_expire_days: int = 7
    # 오늘 푼 문제 수, 연속 학습일 등 '하루'의 기준 시간대
    timezone: str = "Asia/Seoul"
    # 간편 로그인 — 키가 없으면 해당 버튼은 '준비 중'으로 표시된다 (발급 방법은 README 참고)
    # 콘솔에 등록하는 Redirect URI: {public_base_url}/api/auth/{google|kakao}/callback
    public_base_url: str = "http://localhost:8000"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    kakao_rest_api_key: str | None = None
    kakao_client_secret: str | None = None

    # AI (OpenAI) — 키가 없으면 대화 답변은 문제 은행에서 고른다
    # 모델 목록: https://developers.openai.com/api/docs/models
    openai_api_key: str | None = None
    openai_model_generate: str = "gpt-6.1-sol"
    openai_model_verify: str = "gpt-6.1-sol"
    openai_effort_generate: str = "high"
    openai_effort_verify: str = "high"
    ai_max_attempts: int = 2

    # 학교 검색 (나이스 교육정보 개방 포털) — 없어도 되지만 키가 있으면 한 번에 더 많이 찾는다
    neis_api_key: str | None = None  # 검증에 실패하면 문제당 다시 만드는 최대 횟수

    # 다른 출처의 프론트엔드(예: 추후 Next.js 개발 서버)가 API 를 부를 수 있게 허용할 목록.
    # 프로토타입은 API 서버가 /app 으로 함께 서빙하므로 같은 출처라 필요 없다.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
