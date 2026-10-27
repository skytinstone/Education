"""대화 답변.

AI 가 설정되어 있으면 요청에서 개념·난이도·문항 수를 읽어 새 문제를 만들고 검증한다(services/generator.py).
AI 가 없거나 실패하거나 개념을 못 찾으면, 문제 은행의 검증된 문제에서 고른다.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.db import models as m
from education.schemas import Domain, VerificationStatus
from education.services import generator, learning
from education.services.llm import LLMError, get_llm

log = logging.getLogger(__name__)

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


def _from_bank(db: Session, user: m.User, text: str, domain: Domain | None) -> list[str]:
    q = select(m.Problem.id).where(m.Problem.verification == VerificationStatus.VERIFIED, learning.visible_to(user))
    if domain:
        q = q.where(m.Problem.domain == domain)
    return list(db.scalars(q.order_by(func.random()).limit(requested_count(text))))


def project_past_problems(db: Session, user: m.User, project: m.Project, concept_id: str | None = None) -> list[m.Problem]:
    """프로젝트에 올린 기출 문제 (concept_id 를 주면 그 개념만)."""
    q = (select(m.Problem).join(m.Material, m.Material.id == m.Problem.material_id)
         .where(m.Material.project_id == project.id, m.Problem.owner_user_id == user.id))
    if concept_id:
        q = q.join(m.ProblemConcept, m.ProblemConcept.problem_id == m.Problem.id).where(m.ProblemConcept.concept_id == concept_id)
    return list(db.scalars(q.order_by(m.Problem.created_at)))


def reply(db: Session, user: m.User, text: str, project: m.Project | None) -> tuple[str, list[str]]:
    """(답변 문장, 문제 id 목록)"""
    project_domain = db.get(m.Concept, project.subject_id).domain if project else None
    domain = detect_domain(text, project_domain)
    scope = (project.unit_ids or [project.subject_id]) if project else None

    llm = get_llm()
    note = ""
    if llm:
        plan = generator.plan_request(db, text, domain=domain, scope_ids=scope, max_count=MAX_PROBLEMS)
        if plan:
            # 프로젝트에 올린 기출 중 같은 개념의 문제가 있으면 본보기로 쓴다
            exemplars = project_past_problems(db, user, project, plan.concept_id) if project else []
            try:
                report = generator.generate_problems(
                    db, llm, concept_id=plan.concept_id, difficulty=plan.difficulty, count=plan.count, user=user,
                    question_type=project.question_type if project else "multiple_choice",
                    exemplars=exemplars, owner=user if exemplars else None)
            except (LLMError, ValueError) as e:
                log.warning("AI 문제 생성 실패: %s", e)
                report = None
            if report and report.accepted:
                concept = db.get(m.Concept, plan.concept_id)
                dropped = f" (검증을 통과하지 못한 {len(report.rejected)}문제는 뺐어요)" if report.rejected else ""
                return (f"'{concept.name}' 문제 {len(report.accepted)}개를 새로 만들고, 다른 AI가 독립적으로 다시 풀어 "
                        f"정답을 확인했어요{dropped}. 틀린 문제는 오답노트에 자동으로 저장돼요.", report.accepted)
            note = "새 문제를 만들다 검증을 통과하지 못해서, "
        else:
            note = "어떤 개념의 문제인지 찾지 못해서, "

    ids = _from_bank(db, user, text, domain)
    if not ids:
        return "아직 이 과목의 문제가 없어요. 원하는 개념을 조금 더 구체적으로 말해 주세요 (예: 치환적분 3문제).", []
    prefix = note or "AI 연결 전이라 "
    return f"{prefix}문제 은행의 검증된 문제 {len(ids)}개를 보여드려요. 틀린 문제는 오답노트에 자동으로 저장돼요.", ids
