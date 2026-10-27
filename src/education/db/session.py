from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from education.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def session_factory():
    """백그라운드 작업이 쓸 새 세션을 여는 함수 (테스트에서 테스트 DB 세션으로 바꿔 끼운다)."""
    return SessionLocal
