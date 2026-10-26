"""모든 에이전트가 공유하는 핵심 데이터 스키마.

기능 ①~④는 전부 이 스키마 위에서 동작한다.
- Project   : 학습 프로젝트 (목표, 시험일, 범위) — 사이드바의 프로젝트 목록
- Session   : 대화 하나. 프로젝트에 속하거나 독립 대화
- Concept   : 개념 트리의 노드 (과목 > 단원 > 개념)
- Problem   : 생성/기출 문제. 반드시 concept_ids 로 개념 트리에 연결된다.
- Attempt   : 학습자의 풀이 기록 → 오답노트(②)와 약점 분석(③)의 입력
- WrongNote : 오답노트 (원인 분석 + 변형 문제)
- WeaknessReport : 개념별 정답률 기반 약점 리포트
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Domain(StrEnum):
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    EARTH_SCIENCE = "earth_science"


class ConceptLevel(StrEnum):
    SUBJECT = "subject"  # 예: 수학I, 물리학I
    UNIT = "unit"  # 예: 지수함수와 로그함수
    CONCEPT = "concept"  # 예: 로그의 성질


class Concept(BaseModel):
    id: str  # 점 표기 경로, 예: "math.math1.exp_log.log_properties"
    name: str
    domain: Domain
    level: ConceptLevel
    parent_id: str | None = None
    prerequisites: list[str] = Field(default_factory=list)  # 선수 개념 id


class ProblemType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"  # 5지선다
    SHORT_ANSWER = "short_answer"  # 단답형(주관식 정수 등)


class ProblemSource(StrEnum):
    GENERATED = "generated"  # 기능 ①
    VARIANT = "variant"  # 기능 ② 오답 변형
    PAST_EXAM = "past_exam"  # 기출 원문 (내부 분석용)
    PAST_EXAM_STYLE = "past_exam_style"  # 기능 ④ 기출 기반 생성


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"  # 독립 재풀이/코드 검증으로 정답 일치
    REJECTED = "rejected"  # 정답 불일치, 복수 정답, 조건 누락 등


class Problem(BaseModel):
    id: str
    domain: Domain
    concept_ids: list[str] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)  # 1 쉬움 ~ 5 킬러
    problem_type: ProblemType
    stem: str  # 문제 본문 (수식은 LaTeX)
    choices: list[str] | None = None
    answer: str  # 객관식은 "1"~"5", 단답형은 값
    solution: str  # 단계별 해설
    traps: list[str] = Field(default_factory=list)  # 의도된 함정 포인트
    source: ProblemSource
    parent_problem_id: str | None = None  # 변형/기출기반 문제의 원본
    verification: VerificationStatus = VerificationStatus.PENDING

    @model_validator(mode="after")
    def _check_choices(self) -> Problem:
        if self.problem_type is ProblemType.MULTIPLE_CHOICE:
            if not self.choices or len(self.choices) != 5:
                raise ValueError("객관식 문제는 보기 5개가 필요합니다")
            if self.answer not in {"1", "2", "3", "4", "5"}:
                raise ValueError("객관식 정답은 '1'~'5' 중 하나여야 합니다")
        elif self.choices is not None:
            raise ValueError("단답형 문제에는 보기가 없어야 합니다")
        return self


class ErrorType(StrEnum):
    CONCEPT_GAP = "concept_gap"  # 개념 자체를 모름
    MISAPPLICATION = "misapplication"  # 개념은 알지만 적용을 잘못함
    CALCULATION = "calculation"  # 계산 실수
    MISREAD = "misread"  # 조건/문제 오독
    TRAP = "trap"  # 출제자의 함정에 걸림
    TIME_PRESSURE = "time_pressure"  # 시간 부족 / 찍음


class Project(BaseModel):
    id: str
    user_id: str
    name: str  # 예: "2027 수능 미적분"
    goal: str | None = None  # 예: "1등급"
    exam_date: date | None = None  # D-day 표시, 학습 계획 산정
    scope_concept_ids: list[str] = Field(default_factory=list)  # 비어 있으면 범위 제한 없음
    material_ids: list[str] = Field(default_factory=list)  # 업로드 자료 (기출 PDF, 프린트 등)
    created_at: datetime = Field(default_factory=datetime.now)

    def days_left(self, today: date | None = None) -> int | None:
        if self.exam_date is None:
            return None
        return (self.exam_date - (today or date.today())).days


class Session(BaseModel):
    id: str
    user_id: str
    project_id: str | None = None  # None 이면 프로젝트 밖의 독립 대화
    title: str | None = None  # 첫 대화 후 AI 가 자동 생성
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)  # 사이드바 "최근" 정렬 기준


class Attempt(BaseModel):
    user_id: str
    problem_id: str
    project_id: str | None = None  # 프로젝트별 약점 분석용
    session_id: str | None = None
    user_answer: str
    is_correct: bool
    time_spent_sec: int | None = None
    error_type: ErrorType | None = None  # 오답일 때 분석 결과로 채워짐
    created_at: datetime = Field(default_factory=datetime.now)


class WrongNote(BaseModel):
    attempt: Attempt
    error_type: ErrorType
    diagnosis: str  # 왜 틀렸는지 설명
    key_concept_ids: list[str]
    variant_problems: list[Problem]  # 같은 개념, 비슷한 난이도, 다른 형태


class ConceptStat(BaseModel):
    concept_id: str
    attempts: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.attempts if self.attempts else 0.0


class WeaknessReport(BaseModel):
    user_id: str
    weak_concepts: list[ConceptStat]  # 정답률 낮은 순
    dominant_error_types: list[ErrorType]
    summary: str
    created_at: datetime = Field(default_factory=datetime.now)
