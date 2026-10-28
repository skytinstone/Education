# Eureka API 서버 이미지 — 운영 배포용 (docker-compose.prod.yml 이 사용)
# ARM(Oracle Ampere)·x86(AWS EC2) 어느 서버에서나 같은 파일로 빌드된다.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 의존성만 먼저 설치 — 코드만 바뀌었을 때는 이 층을 다시 쓰지 않아 빌드가 빠르다
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY data/concepts ./data/concepts
COPY data/problems ./data/problems
COPY prototype ./prototype
RUN uv sync --locked --no-dev

# root 가 아닌 사용자로 실행. 업로드 폴더는 볼륨으로 붙는다 (기출 파일·프로필 사진)
RUN useradd --system --uid 10001 eureka \
    && mkdir -p data/uploads/avatars \
    && chown -R eureka data/uploads
USER eureka

EXPOSE 8000
# 시작할 때마다 마이그레이션 + 개념·문제 은행 갱신 (둘 다 여러 번 실행해도 안전)
CMD ["sh", "-c", "alembic upgrade head && python -m education.seed && exec uvicorn education.api.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
