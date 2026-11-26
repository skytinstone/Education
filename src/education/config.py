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
    # 대화 첨부의 'Google Drive 에서 고르기' (선택) — 같은 Google Cloud 프로젝트에서 Picker API·Drive API 를 켜고
    # API 키(HTTP 리퍼러를 사이트 주소로 제한)와 프로젝트 번호를 넣는다. 둘 다 있고 GOOGLE_CLIENT_ID 도 있어야 켜진다
    google_picker_api_key: str | None = None
    google_app_id: str | None = None
    kakao_rest_api_key: str | None = None
    kakao_client_secret: str | None = None

    # AI (OpenAI) — 키가 없으면 대화 답변은 문제 은행에서 고른다
    # 모델 목록: https://developers.openai.com/api/docs/models
    openai_api_key: str | None = None
    openai_model_generate: str = "gpt-6.1-sol"
    openai_model_verify: str = "gpt-6.1-sol"
    # 추론 강도: high 는 문제 하나에 1분 넘게 걸려 medium 이 기본 (틀린 문제는 독립 재풀이 검산이 거른다).
    # 더 깊게 풀게 하려면 .env 에 OPENAI_EFFORT_GENERATE=high / OPENAI_EFFORT_VERIFY=high
    # 대화 의도 판단·현황 보고·짧은 답 (services/intent.py) — 메시지마다 부르므로 가볍고 빠른 모델
    openai_model_route: str = "gpt-6-luna"
    openai_effort_route: str = "low"
    openai_effort_generate: str = "medium"
    openai_effort_verify: str = "medium"
    ai_max_attempts: int = 2  # 검증에 실패하면 문제당 다시 만드는 최대 횟수
    # LangChain 에이전트 · RAG (src/education/ai/)
    ai_tool_check: bool = True          # 수학·물리 문제를 SymPy 도구로 한 번 더 검산 (Tool Calling)
    ai_self_correct: bool = True        # 검토에서 떨어지면 이유를 생성 AI 에 알려 고치게 한다 (하네스 3단계)
    ai_tool_check_domains: str = "math,physics"
    ai_chat_agent: bool = True               # 대화의 현황·상담 질문을 도구를 쓰는 에이전트가 답한다
    embedding_model: str = "text-embedding-3-small"
    rag_duplicate_similarity: float = 0.95  # 같은 개념에 이만큼 비슷한 문제가 있으면 중복으로 버린다
    # 한 사람이 하루(서비스 시간대 기준)에 쓸 수 있는 AI — 비용(달러)과 호출 수 중 먼저 닿는 쪽. 0 이면 제한 없음. 운영자는 제외
    ai_daily_limit_usd: float = 0.0   # 계정당 하루 AI 비용 (무료) — 0 이면 제한 없음 (지금은 해제)
    ai_daily_limit_calls: int = 0     # 계정당 하루 AI 호출 수 (무료) — 0 이면 제한 없음 (지금은 해제)
    ai_monthly_limit_usd: float = 0.0  # 계정당 한 달 AI 비용 (무료) — 0 이면 제한 없음 (지금은 해제)
    ai_global_daily_limit_usd: float = 20.0  # 서비스 전체 하루 AI 비용 — 넘으면 운영자 빼고 모두 멈추고 메일 알림

    # 오류 추적 (Sentry). DSN 을 넣으면 서버 오류가 Sentry 로 모인다
    sentry_dsn: str | None = None
    sentry_environment: str = "production"

    # 학교 검색 (나이스 교육정보 개방 포털) — 없어도 되지만 키가 있으면 한 번에 더 많이 찾는다
    neis_api_key: str | None = None
    # 책 검색 (선택) — Google Books 키가 있으면 함께 찾는다. 카카오 책 검색은 KAKAO_REST_API_KEY 를 그대로 쓴다
    google_books_api_key: str | None = None
    # Notion 연결 (선택) — notion.so/my-integrations 에서 '공개 통합'을 만들고 받은 값.
    # 리디렉션 URI: {public_base_url}/api/notion/callback. 둘 다 있어야 설정 화면에 'Notion 연결'이 켜진다
    notion_client_id: str | None = None
    notion_client_secret: str | None = None
    # PortOne V2 월 구독 결제 (services/billing.py). 상점 ID · 채널 키 · API 시크릿이 모두 있어야 요금제 화면이 켜진다.
    # 테스트 채널 키로 먼저 개발하고, 결제 회사 심사가 끝나면 실연동 값으로 바꾼다. 웹훅: {public_base_url}/api/billing/webhook
    portone_store_id: str | None = None
    portone_channel_key: str | None = None
    portone_api_secret: str | None = None
    portone_webhook_secret: str | None = None
    billing_public: bool = False  # false(베타): 요금제 화면은 운영자(ADMIN_EMAILS)에게만 보인다
    usd_krw: float = 1400.0      # 운영 콘솔 매출 탭에서 AI 비용(USD)을 원화로 볼 때의 환율 (대략)
    pg_fee_rate: float = 0.033   # 결제 수수료율 추정 (실제 계약 값으로 바꾼다)

    # 운영자 — 이 이메일로 로그인한 계정만 피드백 관리·문제 복구를 할 수 있다 (쉼표로 여러 개)
    admin_emails: str = ""
    # 새 피드백 메일 알림 (Gmail 은 smtp.gmail.com · 587 · 앱 비밀번호). 비워 두면 보내지 않는다
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    feedback_notify_email: str | None = None  # 받을 주소 (없으면 admin_emails)

    @property
    def admins(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    # 다른 출처의 프론트엔드(예: 추후 Next.js 개발 서버)가 API 를 부를 수 있게 허용할 목록.
    # 프로토타입은 API 서버가 /app 으로 함께 서빙하므로 같은 출처라 필요 없다.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
