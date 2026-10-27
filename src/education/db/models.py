"""PostgreSQL 테이블 정의 (SQLAlchemy 2.0).

src/education/schemas.py 의 Pydantic 스키마와 같은 개념을 저장한다.
- 열거형은 PostgreSQL 네이티브 ENUM 대신 문자열 + CHECK 제약으로 저장해 마이그레이션을 쉽게 한다.
- 사용자 데이터는 모두 user_id 로 소유자를 가지며, 사용자를 지우면 함께 지워진다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from education.schemas import ConceptLevel, Domain, ErrorType, ProblemSource, ProblemType, VerificationStatus


class Base(DeclarativeBase):
    pass


def str_enum(enum_cls, name: str) -> Enum:
    """값(value)을 문자열로 저장하고 CHECK 제약을 거는 열거형 컬럼."""
    return Enum(enum_cls, name=name, native_enum=False, create_constraint=True, length=32,
                values_callable=lambda e: [m.value for m in e])


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------- 사용자 ----------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # 항상 소문자로 저장
    # 이메일 주인이 확인됐는지. 지금은 Google·카카오가 인증한 이메일로 가입한 경우만 true
    # (이메일 가입 인증 메일은 추후). 간편 로그인 계정 자동 연결은 양쪽 모두 인증된 경우에만 한다.
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str | None] = mapped_column(Text)  # 간편 로그인으로만 가입하면 없음
    daily_goal: Mapped[int] = mapped_column(SmallInteger, server_default="20")
    agreed_marketing: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # 프로필 (모두 선택 입력)
    birth_date: Mapped[date | None] = mapped_column(Date)
    school: Mapped[str | None] = mapped_column(String(80))
    major: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(String(200))
    # 프로필 사진: initial(이름 첫 글자) · preset(Eureka 캐릭터) · photo(올린 사진)
    avatar_type: Mapped[str] = mapped_column(String(8), server_default="initial")
    avatar_preset: Mapped[str | None] = mapped_column(String(32))
    avatar_version: Mapped[int] = mapped_column(server_default="0")  # 사진을 바꿀 때마다 +1 (브라우저 캐시 무효화)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("daily_goal BETWEEN 1 AND 200", name="daily_goal_range"),
        CheckConstraint("avatar_type IN ('initial', 'preset', 'photo')", name="user_avatar_type"),
    )


class OAuthAccount(Base):
    """사용자에 연결된 간편 로그인 계정. 한 사용자가 Google 과 카카오를 함께 연결할 수 있다."""
    __tablename__ = "oauth_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_user_id: Mapped[str] = mapped_column(String(128))  # Google sub / 카카오 회원번호
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        CheckConstraint("provider IN ('google', 'kakao')", name="oauth_provider"),
    )


# ---------- 개념 트리 (data/concepts/*.yaml 에서 적재) ----------
class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # 예: math.math1.exp_log.log_properties
    name: Mapped[str] = mapped_column(String(120))
    domain: Mapped[Domain] = mapped_column(str_enum(Domain, "domain"))
    level: Mapped[ConceptLevel] = mapped_column(str_enum(ConceptLevel, "concept_level"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    prerequisites: Mapped[list[str]] = mapped_column(ARRAY(String(120)), server_default="{}")
    curriculum: Mapped[str] = mapped_column(String(32), server_default="2015-revised")


# ---------- 문제 은행 ----------
class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, server_default=text("gen_random_uuid()::text"))
    domain: Mapped[Domain] = mapped_column(str_enum(Domain, "domain"), index=True)
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    problem_type: Mapped[ProblemType] = mapped_column(str_enum(ProblemType, "problem_type"))
    stem: Mapped[str] = mapped_column(Text)
    choices: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    answer: Mapped[str] = mapped_column(String(64))
    solution: Mapped[str] = mapped_column(Text)
    traps: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    source: Mapped[ProblemSource] = mapped_column(str_enum(ProblemSource, "problem_source"))
    parent_problem_id: Mapped[str | None] = mapped_column(ForeignKey("problems.id", ondelete="SET NULL"))
    verification: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus, "verification_status"), server_default=VerificationStatus.PENDING.value)
    # AI 생성 문제: 생성·검증 모델, 검증자가 고른 답, 지적 사항 등 (사람이 만든 문제는 null)
    generation_meta: Mapped[dict | None] = mapped_column(JSONB)
    # 소유자: null 이면 모두가 쓰는 공용 문제. 사용자가 올린 기출과 그것을 바탕으로 만든 문제는
    # 저작권 때문에 올린 사람에게만 보인다.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = created_at()

    concepts: Mapped[list[Concept]] = relationship(secondary="problem_concepts", lazy="selectin")

    __table_args__ = (CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),)

    @property
    def concept_ids(self) -> list[str]:
        return [c.id for c in self.concepts]


class ProblemConcept(Base):
    __tablename__ = "problem_concepts"

    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True, index=True)


# ---------- 학습 프로젝트 · 대화 ----------
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    subject_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    unit_ids: Mapped[list[str]] = mapped_column(ARRAY(String(120)), server_default="{}")  # 비어 있으면 과목 전체
    goal: Mapped[str] = mapped_column(String(60), server_default="")
    exam_date: Mapped[date | None] = mapped_column(Date)
    question_type: Mapped[str] = mapped_column(String(16), server_default="multiple_choice")  # multiple_choice | short_answer | mixed
    pinned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("question_type IN ('multiple_choice', 'short_answer', 'mixed')", name="project_question_type"),)


class Material(Base):
    """사용자가 올린 기출·시험지 (PDF·사진). AI 가 문제를 뽑아 내 problems 에 PAST_EXAM 으로 저장한다."""
    __tablename__ = "materials"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    storage_path: Mapped[str] = mapped_column(Text)  # 업로드 폴더(data/uploads) 기준 상대 경로, 추후 객체 저장소
    status: Mapped[str] = mapped_column(String(16), server_default="uploaded")  # uploaded | extracting | ready | failed
    error: Mapped[str | None] = mapped_column(Text)
    problem_count: Mapped[int] = mapped_column(server_default="0")
    rights_confirmed: Mapped[bool] = mapped_column(Boolean)  # "학습용으로 쓸 수 있는 자료" 확인
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("status IN ('uploaded', 'extracting', 'ready', 'failed')", name="material_status"),)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # 프로젝트를 지우면 그 안의 대화도 함께 지운다 (화면 동작과 동일)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="session", order_by="Message.created_at", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(8))  # user | ai
    text: Mapped[str] = mapped_column(Text)
    problem_ids: Mapped[list[str]] = mapped_column(ARRAY(String(64)), server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    __table_args__ = (CheckConstraint("role IN ('user', 'ai')", name="message_role"),)


# ---------- 풀이 기록 · 오답노트 ----------
class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    # 프로젝트·대화가 지워져도 풀이 기록은 남긴다
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="SET NULL"), index=True)
    answer: Mapped[str] = mapped_column(String(64))
    correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

    __table_args__ = (Index("ix_attempts_user_created", "user_id", "created_at"),)


class WrongNote(Base):
    __tablename__ = "wrong_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    answer: Mapped[str] = mapped_column(String(64))  # 처음 틀렸을 때 고른 답
    error_type: Mapped[ErrorType] = mapped_column(str_enum(ErrorType, "error_type"), server_default=ErrorType.UNKNOWN.value)
    created_at: Mapped[datetime] = created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 다시 풀어 맞힌 시각

    __table_args__ = (
        Index("ix_wrong_notes_user_created", "user_id", "created_at"),
        # 한 문제에 '아직 극복 못 한' 오답은 하나만
        Index("uq_wrong_notes_open", "user_id", "problem_id", unique=True, postgresql_where=text("resolved_at IS NULL")),
    )


# ---------- 라이브러리 ----------
class Card(Base):
    __tablename__ = "cards"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    known: Mapped[bool | None] = mapped_column(Boolean)  # None: 아직 안 봄
    created_at: Mapped[datetime] = created_at()


class LLMCall(Base):
    """AI 호출 기록 — 문제 1개당 실제 비용·시간을 측정하고 모델을 비교하는 데 쓴다."""
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    purpose: Mapped[str] = mapped_column(String(16))  # generate | verify
    model: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(server_default="0")
    cached_tokens: Mapped[int] = mapped_column(server_default="0")
    output_tokens: Mapped[int] = mapped_column(server_default="0")
    reasoning_tokens: Mapped[int] = mapped_column(server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int] = mapped_column(server_default="0")
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    problem_id: Mapped[str | None] = mapped_column(ForeignKey("problems.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = created_at()


class SavedProblem(Base):
    __tablename__ = "saved_problems"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = created_at()
