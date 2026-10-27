"""API 테스트 공통 준비.

- 테스트 DB(TEST_DATABASE_URL)를 비우고 '실제 마이그레이션'으로 테이블을 만든다 → 마이그레이션도 함께 검증
- 개념 트리와 문제 은행을 넣고, 테스트마다 트랜잭션을 되돌려 서로 영향을 주지 않게 한다
"""

import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from education.config import ROOT, get_settings
from education.seed import seed_concepts, seed_problems


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch):
    """테스트는 절대 실제 AI API 를 부르지 않는다 (.env 에 키가 있어도). AI 가 필요한 테스트는 가짜 LLM 을 넣는다."""
    monkeypatch.setattr(get_settings(), "openai_api_key", None)


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL 이 없어요 (.env.example 참고)")
    return url


@pytest.fixture(scope="session")
def engine(test_db_url):
    eng = create_engine(test_db_url)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    except OperationalError:
        pytest.skip("테스트 DB에 연결할 수 없어요 — `docker compose up -d` 로 DB를 켜 주세요")
    subprocess.run(["alembic", "-x", f"db_url={test_db_url}", "upgrade", "head"], cwd=ROOT, check=True, capture_output=True)
    with Session(eng) as s, s.begin():
        seed_concepts(s)
        seed_problems(s)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def client(db):
    from education.api.main import app
    from education.db.session import get_db

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def signup(client, name="민석", email=None, password="abc12345") -> dict:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={
        "name": name, "email": email, "password": password, "over_14": True, "agreed_terms": True})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def new_user(client):
    """새 사용자를 가입시키고 인증 헤더를 돌려주는 함수."""
    return lambda **kw: signup(client, **kw)


@pytest.fixture
def auth(new_user) -> dict:
    return new_user()
