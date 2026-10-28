"""API 요청·응답 모델.

문제 정답(answer)과 해설(solution)은 학생이 답을 제출한 뒤에만 내려보낸다.
아직 안 푼 문제는 ProblemOut 으로만 보여 주므로 개발자 도구로도 정답을 볼 수 없다.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from education.schemas import ConceptLevel, Domain, ErrorType


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 인증 · 사용자 ----------
def _must_agree(v: bool) -> bool:
    if not v:
        raise ValueError("필수 항목에 동의해야 가입할 수 있어요")
    return v


RequiredAgree = Annotated[bool, AfterValidator(_must_agree)]


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    over_14: RequiredAgree  # 만 14세 이상
    agreed_terms: RequiredAgree  # 이용약관 + 개인정보 수집·이용
    agreed_marketing: bool = False

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("비밀번호는 영문과 숫자를 함께 써야 해요")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(Out):
    id: UUID
    email: str
    name: str
    daily_goal: int
    birth_date: date | None = None
    school: str | None = None
    major: str | None = None
    address: str | None = None
    avatar_type: str = "initial"
    avatar_preset: str | None = None
    avatar_version: int = 0

    @computed_field
    @property
    def avatar_url(self) -> str | None:
        return f"/api/users/{self.id}/avatar?v={self.avatar_version}" if self.avatar_type == "photo" else None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TicketIn(BaseModel):
    ticket: str


class SocialSignupIn(BaseModel):
    """간편 로그인으로 처음 온 사용자의 약관 동의. 이메일을 못 받은 경우(카카오 이메일 미동의)에만 email 을 입력받는다."""
    signup_token: str
    email: EmailStr | None = None
    over_14: RequiredAgree
    agreed_terms: RequiredAgree
    agreed_marketing: bool = False


class AccountDeleteIn(BaseModel):
    """회원 탈퇴 — 실수로 누르지 않도록 내 이메일을 그대로 입력받는다."""
    confirm_email: str


class UserPatch(BaseModel):
    """보낸 필드만 바꾼다. 학교·전공·주소·생년월일은 빈 값("" 또는 null)을 보내면 지운다."""
    name: str | None = Field(default=None, min_length=1, max_length=40)
    daily_goal: int | None = Field(default=None, ge=1, le=200)
    birth_date: date | None = None
    school: str | None = Field(default=None, max_length=80)
    major: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    avatar: str | None = Field(default=None, description="initial 또는 Eureka 캐릭터 이름 (사진은 POST /me/avatar)")

    @field_validator("birth_date")
    @classmethod
    def _birth(cls, v: date | None) -> date | None:
        if v and not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("생년월일을 확인해 주세요")
        return v


# ---------- 개념 · 문제 ----------
class ConceptOut(Out):
    id: str
    name: str
    domain: Domain
    level: ConceptLevel
    parent_id: str | None
    prerequisites: list[str]


class ProblemOut(Out):
    """정답·해설을 뺀 문제."""
    id: str
    domain: Domain
    concept_ids: list[str]
    difficulty: int
    problem_type: str
    stem: str
    choices: list[str] | None


class AttemptView(BaseModel):
    answer: str
    correct: bool


class ProblemView(ProblemOut):
    """대화·라이브러리에서 보여 주는 문제. 푼 적이 있으면 정답·해설도 함께."""
    attempt: AttemptView | None = None
    answer: str | None = None
    solution: str | None = None
    saved: bool = False


class AttemptIn(BaseModel):
    problem_id: str
    answer: str = Field(min_length=1, max_length=64)
    project_id: UUID | None = None
    session_id: UUID | None = None


class AttemptResult(BaseModel):
    correct: bool
    answer: str  # 정답
    solution: str
    wrong_note_id: UUID | None = None  # 틀려서 오답노트에 있으면
    resolved: bool = False  # 이번 풀이로 오답을 극복했으면


# ---------- 프로젝트 · 대화 ----------
QuestionType = Literal["multiple_choice", "short_answer", "mixed"]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    subject_id: str
    unit_ids: list[str] = []
    goal: str = Field(default="", max_length=60)
    exam_date: date | None = None
    question_type: QuestionType = "multiple_choice"


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    subject_id: str | None = None
    unit_ids: list[str] | None = None
    goal: str | None = Field(default=None, max_length=60)
    exam_date: date | None = None
    question_type: QuestionType | None = None
    pinned: bool | None = None


class ProjectOut(Out):
    id: UUID
    name: str
    subject_id: str
    unit_ids: list[str]
    goal: str
    exam_date: date | None
    question_type: str
    pinned: bool
    created_at: datetime


class MaterialOut(Out):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str  # uploaded | extracting | ready | failed
    error: str | None
    problem_count: int
    created_at: datetime


class PastProblemOut(ProblemOut):
    number: int | None
    has_answer: bool
    needs_figure: bool


class GenerateIn(BaseModel):
    """기출 기반 문제 만들기 — 기출보다 쉽게 / 비슷하게 / 어렵게."""
    level: Literal["easier", "same", "harder"] = "same"
    count: int = Field(default=3, ge=1, le=5)
    concept_id: str | None = None


class WeakConcept(BaseModel):
    concept_id: str
    name: str
    attempts: int
    correct: int
    accuracy: float


class ProjectSummary(BaseModel):
    project: ProjectOut
    attempts: int
    accuracy: float | None
    open_notes: int
    weak_concepts: list[WeakConcept]


class SessionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    project_id: UUID | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SessionPatch(BaseModel):
    """보낸 필드만 바꾼다. project_id 를 null 로 보내면 프로젝트에서 뺀다."""
    title: str | None = Field(default=None, min_length=1, max_length=80)
    project_id: UUID | None = None


class SessionOut(Out):
    id: UUID
    project_id: UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: UUID
    role: str
    text: str
    problems: list[ProblemView]
    created_at: datetime


class SessionDetail(SessionOut):
    messages: list[MessageOut]


# ---------- 오답노트 · 카드 · 통계 ----------
class WrongNoteOut(BaseModel):
    id: UUID
    problem: ProblemOut
    project_id: UUID | None
    answer: str
    error_type: ErrorType
    created_at: datetime
    resolved_at: datetime | None


class WrongNotePatch(BaseModel):
    error_type: ErrorType


class CardOut(Out):
    id: UUID
    concept_id: str
    front: str
    back: str
    known: bool | None


class CardPatch(BaseModel):
    known: bool | None


class SolutionReviewIn(BaseModel):
    """서술형 풀이 — 타이핑한 글, 손글씨 캔버스(PNG data URL) 중 하나 이상."""
    text: str | None = Field(default=None, max_length=4000)
    image: str | None = Field(default=None, max_length=5_000_000)

    @field_validator("image")
    @classmethod
    def _png(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("data:image/png;base64,"):
            raise ValueError("손글씨는 PNG 이미지여야 해요")
        return v


class ConceptNoteOut(Out):
    """내 맞춤 개념 정리 — content 는 services/notes.py 의 NoteContent
    (summary, must_memorize[{title, body}], pitfalls, example{question, solution}, personal_tip)."""
    concept_id: str
    content: dict
    created_at: datetime


class ConceptNoteCreated(BaseModel):
    note: ConceptNoteOut
    added_cards: list[CardOut]  # 이번에 내 카드 덱에 새로 들어간 카드 (이미 있던 것과 겹치면 빠짐)


class StatsOut(BaseModel):
    today_count: int
    daily_goal: int
    streak: int
    open_notes: int
    accuracy_by_domain: dict[Domain, float | None]
    weak_concepts: list[WeakConcept]


class ConceptDetail(BaseModel):
    concept: ConceptOut
    path: list[ConceptOut]
    next_concepts: list[ConceptOut]
    stats: WeakConcept | None
    problems: list[ProblemView]
    cards: list[CardOut]
