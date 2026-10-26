"""API 요청·응답 모델.

문제 정답(answer)과 해설(solution)은 학생이 답을 제출한 뒤에만 내려보낸다.
아직 안 푼 문제는 ProblemOut 으로만 보여 주므로 개발자 도구로도 정답을 볼 수 없다.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator

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


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    daily_goal: int | None = Field(default=None, ge=1, le=200)


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
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    subject_id: str
    unit_ids: list[str] = []
    goal: str = Field(default="", max_length=60)
    exam_date: date | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    subject_id: str | None = None
    unit_ids: list[str] | None = None
    goal: str | None = Field(default=None, max_length=60)
    exam_date: date | None = None
    pinned: bool | None = None


class ProjectOut(Out):
    id: UUID
    name: str
    subject_id: str
    unit_ids: list[str]
    goal: str
    exam_date: date | None
    pinned: bool
    created_at: datetime


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
