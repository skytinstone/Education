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
    Integer,
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

from education.schemas import ConceptLevel, ErrorType, ProblemSource, ProblemType, VerificationStatus


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
    # 운영자가 이용을 정지한 계정 — 로그인과 모든 API 가 막힌다 (운영 콘솔에서 해제)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(String(500))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 접속 상태 (운영 콘솔 '회원') — 로그인된 화면이 1분마다 알리고, API 요청 때도 갱신한다 (1분에 한 번만 씀)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_ip: Mapped[str | None] = mapped_column(String(64))
    last_seen_ua: Mapped[str | None] = mapped_column(String(300))
    last_seen_page: Mapped[str | None] = mapped_column(String(24))  # 보고 있던 화면 종류 (home · chat · project …)
    # 동시 접속 막기 — 로그인할 때마다 새로 정하고 토큰에 넣는다. 토큰의 값과 다르면 다른 곳에서 다시 로그인한 것
    session_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("daily_goal BETWEEN 1 AND 200", name="daily_goal_range"),
        CheckConstraint("avatar_type IN ('initial', 'preset', 'photo')", name="user_avatar_type"),
    )


class ExamRecord(Base):
    """화면에서 본 시험 한 번 — 점수·걸린 시간·문항별 결과 (점수 추이·오래 걸린 문항)."""
    __tablename__ = "exam_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str | None] = mapped_column(String(80))  # 자료 id 또는 all
    per: Mapped[int] = mapped_column(SmallInteger, server_default="1")  # 한 화면에 1 · 4 문제
    time_limit_sec: Mapped[int | None] = mapped_column(Integer)
    used_sec: Mapped[int] = mapped_column(Integer)
    auto_submitted: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 시간이 다 돼서 저절로 제출
    score: Mapped[int] = mapped_column(SmallInteger)
    total_points: Mapped[int] = mapped_column(SmallInteger)
    correct: Mapped[int] = mapped_column(SmallInteger)
    total: Mapped[int] = mapped_column(SmallInteger)
    skipped: Mapped[int] = mapped_column(SmallInteger)
    ungraded: Mapped[int] = mapped_column(SmallInteger)
    # [{problem_id, number, my, answer, correct, points, sec}]
    items: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (Index("ix_exam_records_user_created", "user_id", "created_at"),)


class AdminAction(Base):
    """운영자가 한 조치 기록 — 누가 언제 누구에게 무엇을 했는지 (정지·해제·삭제·강제 로그아웃·VOC·공지).
    대상 계정이 지워져도 기록은 남도록 대상은 외래 키 없이 id·이메일로 적는다."""
    __tablename__ = "admin_actions"

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    admin_email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(24))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    target_email: Mapped[str | None] = mapped_column(String(320))
    detail: Mapped[str | None] = mapped_column(String(1000))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

    __table_args__ = (Index("ix_admin_actions_created", "created_at"),)


class LoginEvent(Base):
    """로그인·가입 기록 (성공과 실패 모두). 개인정보처리방침의 '로그 데이터' — 90일이 지나면 지운다 (services/audit.py).
    없는 이메일로 실패한 시도도 남기도록 user_id 는 비어 있을 수 있다."""
    __tablename__ = "login_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    method: Mapped[str] = mapped_column(String(16))  # password · google · kakao
    kind: Mapped[str] = mapped_column(String(8), server_default="login")  # login · signup
    ok: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(32))  # 실패 이유: bad_credentials · suspended
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    # now() 는 트랜잭션 시작 시각이라, 한 요청 안의 여러 기록도 순서가 갈리도록 실제 시각을 쓴다
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

    __table_args__ = (
        CheckConstraint("method IN ('password', 'google', 'kakao')", name="login_event_method"),
        CheckConstraint("kind IN ('login', 'signup')", name="login_event_kind"),
        Index("ix_login_events_created", "created_at"),
    )


class SiteVisit(Base):
    """오늘 방문자 수 — 브라우저마다 익명 id 하나, 하루에 한 번만 센다 (로그인 화면의 '오늘 방문자').
    IP 는 원문 대신 서명 키로 만든 해시만 남기고(같은 IP 의 부풀리기 제한용), 90일 뒤 지운다."""
    __tablename__ = "site_visits"

    id: Mapped[uuid.UUID] = uuid_pk()
    day: Mapped[date] = mapped_column(Date)
    visitor_id: Mapped[str] = mapped_column(String(36))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("day", "visitor_id", name="uq_site_visit_day_visitor"),
        Index("ix_site_visits_day_ip", "day", "ip_hash"),
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
class Course(Base):
    """코스 — 시험·과목·교재·범위를 묶은 학습 단위. id 는 개념 트리 뿌리(level=subject) 개념의 id 와 같다.
    공식 템플릿(source=template, data/concepts 시드)과 사용자가 출제 범위로 만든 코스(source=user)가 있고 모두 공개."""
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    exam: Mapped[str] = mapped_column(String(120), server_default="")  # 수능, 편입, CPA 1차 …
    category: Mapped[str] = mapped_column(String(40))  # 분야 표시 이름 (수학, 회계 …)
    domain: Mapped[str] = mapped_column(String(32))  # 분야 키 (math … / general) — 색·분류용
    level: Mapped[str] = mapped_column(String(40), server_default="")  # 고등, 대학, 자격증 …
    curriculum: Mapped[str] = mapped_column(String(60), server_default="")
    textbook: Mapped[str] = mapped_column(String(200), server_default="")
    textbook_isbn: Mapped[str | None] = mapped_column(String(13))  # 선택
    language: Mapped[str] = mapped_column(String(8), server_default="ko")
    scope_text: Mapped[str | None] = mapped_column(Text)  # 사용자가 붙여넣은 출제 범위 원문
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(60)), server_default="{}")  # 요청 문장에서 알아들을 이름
    choice_count: Mapped[int] = mapped_column(SmallInteger, server_default="5")  # 객관식 보기 개수 (토익 4, 수능 5)
    formats: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default="{}")  # 시험 문제 형식 (비면 객관식)
    source: Mapped[str] = mapped_column(String(12), server_default="user")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("source IN ('template', 'user')", name="course_source"),)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # 예: math.math1.exp_log.log_properties
    name: Mapped[str] = mapped_column(String(120))
    domain: Mapped[str] = mapped_column(String(32))  # 코스의 분야 키
    level: Mapped[ConceptLevel] = mapped_column(str_enum(ConceptLevel, "concept_level"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    prerequisites: Mapped[list[str]] = mapped_column(ARRAY(String(120)), server_default="{}")
    curriculum: Mapped[str] = mapped_column(String(32), server_default="2015-revised")
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(server_default="0")  # 형제 사이 순서


# ---------- 문제 은행 ----------
class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, server_default=text("gen_random_uuid()::text"))
    domain: Mapped[str] = mapped_column(String(32), index=True)
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    problem_type: Mapped[ProblemType] = mapped_column(str_enum(ProblemType, "problem_type"))
    stem: Mapped[str] = mapped_column(Text)
    choices: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    answer: Mapped[str] = mapped_column(Text)  # 객관식은 보기 번호, 그 밖에는 값 (서술형은 모범 답안)
    # 형식별 채점 정보 — text: {accepted}, numeric: {unit, tolerance}, essay: {rubric, max_score}
    answer_spec: Mapped[dict | None] = mapped_column(JSONB)
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


class ProblemAnswer(Base):
    """올린 문제지의 문항 하나 ↔ 정답 하나 (problem_id 가 기본키라 1:1).

    정답의 출처를 나눠 둔다: 문제지·정답 파일에 적힌 답(sheet_*), AI 가 푼 답과 해설(ai_*), 정답을 모르고 다시 푼 답(check_answer).
    problems.answer·verification 은 이 행에서 계산한다 (services/answer_key.py refresh)."""
    __tablename__ = "problem_answers"

    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    number: Mapped[int | None]
    sheet_answer: Mapped[str] = mapped_column(String(200), server_default="")
    printed_answer: Mapped[str] = mapped_column(String(200), server_default="")  # 문제지에 인쇄돼 있던 정답 (정답 파일을 빼면 이것으로 돌아감)
    sheet_explanation: Mapped[str | None] = mapped_column(Text)
    # 정답이 별도 정답 파일에서 왔으면 그 자료 (문제지에 인쇄된 정답이면 비어 있음)
    sheet_material_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"), index=True)
    ai_answer: Mapped[str | None] = mapped_column(String(200))
    ai_solution: Mapped[str | None] = mapped_column(Text)
    check_answer: Mapped[str | None] = mapped_column(String(200))
    # 사용자가 매핑 화면에서 직접 고친 정답 — 다른 모든 출처보다 우선 (비우면 원래 계산으로 돌아감)
    manual_answer: Mapped[str | None] = mapped_column(String(200))
    # manual(직접 입력) · sheet(정답만) · confirmed · conflict · verified · uncertain · failed
    status: Mapped[str | None] = mapped_column(String(12))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (CheckConstraint(
        "status IN ('manual', 'sheet', 'confirmed', 'conflict', 'verified', 'uncertain', 'failed')", name="problem_answer_status"),)


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
    # 공부하는 교재 (예: "수능특강 미적분, 쎈 수학Ⅰ") — 문제 생성·개념 정리가 이 교재의 단원 순서·문제 유형을 참고한다
    textbook: Mapped[str] = mapped_column(String(120), server_default="")
    textbook_isbn: Mapped[str | None] = mapped_column(String(13))  # 선택 — 책 검색에서 고르면 채워진다
    exam_date: Mapped[date | None] = mapped_column(Date)
    question_type: Mapped[str] = mapped_column(String(16), server_default="auto")  # schemas.QUESTION_TYPES
    pinned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint(
        "question_type IN ('auto', 'multiple_choice', 'short_answer', 'text', 'numeric', 'essay', 'mixed')",
        name="project_question_type"),)


class Material(Base):
    """사용자가 올린 기출·시험지 또는 교재 페이지 (PDF·사진). AI 가 문제를 뽑아 problems 에 PAST_EXAM·TEXTBOOK 으로
    저장하고 (올린 사람에게만 보임), 새 문제를 만들 때 본보기로 쓴다."""
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
    kind: Mapped[str] = mapped_column(String(12), server_default="past_exam")  # past_exam | textbook | answer_sheet
    # 정답 파일(answer_sheet)이면 어느 문제지의 정답인지 — 문제지 하나에 정답 파일 하나 (UNIQUE, 1:1)
    answer_for_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), unique=True)
    # 정답 파일 매핑 결과: {"matched": n, "total": 문제 수, "missing": [정답 없는 번호], "extra": [문제지에 없는 번호]}
    answer_map: Mapped[dict | None] = mapped_column(JSONB)
    # 정답지 (services/answer_key.py): 없음(null) → running → done | failed
    answer_key_status: Mapped[str | None] = mapped_column(String(12))
    answer_key_error: Mapped[str | None] = mapped_column(Text)
    answer_key_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_key_done: Mapped[int] = mapped_column(server_default="0")  # 진행률: 풀이를 마친 문항 수
    answer_key_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 오래 멈춘 작업을 가려내는 데 씀
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("status IN ('uploaded', 'extracting', 'ready', 'failed')", name="material_status"),
                      CheckConstraint("kind IN ('past_exam', 'textbook', 'answer_sheet')", name="material_kind"),
                      CheckConstraint("answer_key_status IN ('running', 'done', 'failed')", name="material_answer_key_status"))


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
    # 계산·설명 질문의 풀이 (결과·원리·단계·그래프·검산, services/explain.py). 문제를 낸 답변이면 비어 있다
    explanation: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    attachments: Mapped[list[ChatFile]] = relationship(order_by="ChatFile.created_at", passive_deletes=True)

    __table_args__ = (CheckConstraint("role IN ('user', 'ai')", name="message_role"),)


class ChatFile(Base):
    """대화 입력창 + 로 첨부한 사진·PDF (services/chat_files.py).

    먼저 올려 id 를 받고(message_id 없음), 메시지를 보낼 때 그 메시지에 묶인다. 올린 사람만 볼 수 있다.
    대화를 지우면 행은 함께 지워지고, 디스크 파일은 지우는 쪽(라우터)이 거둔다.
    """
    __tablename__ = "chat_files"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(512))  # UPLOAD_DIR 기준 상대 경로
    created_at: Mapped[datetime] = created_at()


# ---------- 풀이 기록 · 오답노트 ----------
class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    # 프로젝트·대화가 지워져도 풀이 기록은 남긴다
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="SET NULL"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(SmallInteger)  # 서술형 점수 (AI 채점)
    feedback: Mapped[dict | None] = mapped_column(JSONB)  # 서술형 채점 결과 (기준별 점수·한마디)
    correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

    __table_args__ = (Index("ix_attempts_user_created", "user_id", "created_at"),)


class WrongNote(Base):
    __tablename__ = "wrong_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    answer: Mapped[str] = mapped_column(Text)  # 처음 틀렸을 때 고른 답
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


class Feedback(Base):
    """사용자 의견과 문제 신고. 같은 공용 문제를 서로 다른 두 사람이 신고하면 자동으로 숨긴다 (services/feedback.py)."""
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # problem · solution · review · feature · bug · other
    message: Mapped[str] = mapped_column(Text)
    problem_id: Mapped[str | None] = mapped_column(ForeignKey("problems.id", ondelete="SET NULL"), index=True)
    page: Mapped[str | None] = mapped_column(String(200))  # 보내던 화면 (#/chat/… 등)
    status: Mapped[str] = mapped_column(String(12), server_default="open")  # open · reviewing · resolved
    reply: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("kind IN ('problem', 'solution', 'review', 'feature', 'bug', 'other')", name="feedback_kind"),
        CheckConstraint("status IN ('open', 'reviewing', 'resolved')", name="feedback_status"),
        Index("ix_feedback_status_created", "status", "created_at"),
    )


class Notification(Base):
    """알림 — 기출 분석 완료·피드백 답변·공지는 일이 생길 때 바로, 복습·D-day·카드·연속 학습은 하루 한 번 계산해서 만든다.
    key 가 있으면 사용자마다 한 번만 만든다 (예: "dday:프로젝트id:7")."""
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200))  # 누르면 갈 화면 (#/project/… 등)
    key: Mapped[str | None] = mapped_column(String(120))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("kind IN ('material', 'feedback_reply', 'announcement', 'review_due', 'exam_dday', 'cards_due', 'streak')",
                        name="notification_kind"),
        UniqueConstraint("user_id", "key", name="uq_notification_user_key"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )


class ConceptNote(Base):
    """사용자마다 따로 만드는 AI 개념 정리 — 그 사람의 풀이·오답 기록에 맞춘다.
    검증 에이전트를 통과한 것만 저장하고, 다시 만들면 덮어쓴다."""
    __tablename__ = "concept_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    content: Mapped[dict] = mapped_column(JSONB)  # 핵심 정리·필수 암기·자주 틀리는 점·예제 (services/notes.py 의 NoteContent)
    generation_meta: Mapped[dict | None] = mapped_column(JSONB)  # 모델, 검증자 지적 사항, 개인화에 쓴 기록 요약
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (UniqueConstraint("user_id", "concept_id", name="uq_concept_note_user_concept"),)


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

    __table_args__ = (Index("ix_llm_calls_created", "created_at"),)  # 운영 콘솔의 기간별 사용량


class SavedProblem(Base):
    __tablename__ = "saved_problems"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = created_at()
