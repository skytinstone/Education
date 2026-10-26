"""대화 답변 — AI 연결 전 임시 구현.

요청 문장에서 과목과 문항 수를 읽어 문제 은행에서 검증된 문제를 고른다.
LLM 에이전트(문제 생성 + 검증)를 붙이면 reply() 만 바꾸면 된다.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.db import models as m
from education.schemas import Domain, VerificationStatus

KEYWORDS: list[tuple[Domain, re.Pattern]] = [
    (Domain.MATH, re.compile(r"수학|미적|적분|미분|로그|수열|확률|함수|모의고사")),
    (Domain.PHYSICS, re.compile(r"물리|운동|역학|가속|운동량|속력")),
    (Domain.CHEMISTRY, re.compile(r"화학|몰|중화|산화|염기|분자")),
    (Domain.BIOLOGY, re.compile(r"생명|생물|염색체|유전|세포")),
    (Domain.EARTH_SCIENCE, re.compile(r"지구|별|H-R|반감기|지층|은하")),
]
MAX_PROBLEMS = 3


def detect_domain(text: str, fallback: Domain | None = None) -> Domain | None:
    for domain, pattern in KEYWORDS:
        if pattern.search(text):
            return domain
    return fallback


def requested_count(text: str) -> int:
    match = re.search(r"(\d+)\s*(문제|문항|개)", text)
    return max(1, min(int(match.group(1)) if match else 2, MAX_PROBLEMS))


def reply(db: Session, text: str, project_domain: Domain | None) -> tuple[str, list[str]]:
    """(답변 문장, 문제 id 목록)"""
    domain = detect_domain(text, project_domain)
    q = select(m.Problem.id).where(m.Problem.verification == VerificationStatus.VERIFIED)
    if domain:
        q = q.where(m.Problem.domain == domain)
    ids = list(db.scalars(q.order_by(func.random()).limit(requested_count(text))))
    if not ids:
        return "아직 이 과목의 문제가 문제 은행에 없어요. AI 연결 후 바로 만들어 드릴게요.", []
    return f"AI 연결 전이라 문제 은행의 샘플 문제 {len(ids)}개를 보여드려요. 틀린 문제는 오답노트에 자동으로 저장돼요.", ids
