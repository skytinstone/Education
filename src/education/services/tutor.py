"""대화 답변.

먼저 무엇을 원하는지 판단한다 (services/intent.py — 이전 대화·학습 현황을 함께 본다).
문제 요청이면 개념·난이도·문항 수를 읽어 새 문제를 만들고 검증한다(services/generator.py).
AI 가 없거나 실패하거나 개념을 못 찾으면, 문제 은행의 검증된 문제에서 고른다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from education.db import models as m
from education.schemas import Domain, VerificationStatus
from education.services import explain, generator, intent, learning, quota
from education.services.llm import Attachment, LLMError, get_llm

log = logging.getLogger(__name__)

KEYWORDS: list[tuple[Domain, re.Pattern]] = [
    (Domain.MATH, re.compile(r"수학|미적|적분|미분|로그|수열|확률|함수|모의고사")),
    (Domain.PHYSICS, re.compile(r"물리|운동|역학|가속|운동량|속력")),
    (Domain.CHEMISTRY, re.compile(r"화학|몰|중화|산화|염기|분자")),
    (Domain.BIOLOGY, re.compile(r"생명|생물|염색체|유전|세포")),
    (Domain.EARTH_SCIENCE, re.compile(r"지구|별|H-R|반감기|지층|은하")),
]
MAX_PROBLEMS = 5


def detect_domain(text: str, fallback: Domain | None = None) -> Domain | None:
    for domain, pattern in KEYWORDS:
        if pattern.search(text):
            return domain
    return fallback


def requested_count(text: str) -> int:
    match = re.search(r"(\d+)\s*(문제|문항|개)", text)
    return max(1, min(int(match.group(1)) if match else 2, MAX_PROBLEMS))


def _from_bank(db: Session, user: m.User, text: str, domain: Domain | None, scope: list[str] | None) -> list[str]:
    """검증된 문제 중에서 고른다. 과목·단원 범위가 정해지면 그 안에서만 (같은 수학이라도 다른 과목은 섞지 않음)."""
    q = select(m.Problem.id).where(m.Problem.verification == VerificationStatus.VERIFIED, learning.visible_to(user))
    if scope:
        q = q.where(m.Problem.id.in_(select(m.ProblemConcept.problem_id).where(
            or_(*(or_(m.ProblemConcept.concept_id == s, m.ProblemConcept.concept_id.startswith(f"{s}.")) for s in scope)))))
    elif domain:
        q = q.where(m.Problem.domain == domain)
    return list(db.scalars(q.order_by(func.random()).limit(requested_count(text))))


def project_past_problems(db: Session, user: m.User, project: m.Project, concept_id: str | None = None) -> list[m.Problem]:
    """프로젝트에 올린 기출 문제 (concept_id 를 주면 그 개념만)."""
    q = (select(m.Problem).join(m.Material, m.Material.id == m.Problem.material_id)
         .where(m.Material.project_id == project.id, m.Problem.owner_user_id == user.id))
    if concept_id:
        q = q.join(m.ProblemConcept, m.ProblemConcept.problem_id == m.Problem.id).where(m.ProblemConcept.concept_id == concept_id)
    return list(db.scalars(q.order_by(m.Problem.created_at)))


def textbook_label(project: m.Project) -> str | None:
    """AI 에게 줄 교재 이름 (ISBN 이 있으면 함께 — 판을 구분하는 데 도움이 된다)."""
    if not project.textbook:
        return None
    return f"{project.textbook} (ISBN {project.textbook_isbn})" if project.textbook_isbn else project.textbook


class Stopped(Exception):
    """학생이 '답변 멈추기' 를 눌렀다 — 다음 단계(문제 만들기·풀이)로 가지 않는다."""


@dataclass
class Reply:
    text: str
    problem_ids: list[str] = field(default_factory=list)
    explanation: dict | None = None
    intent: str | None = None          # services/intent.py 의 판단 (글자 기준·AI 판단 모두)
    suggestions: list[str] = field(default_factory=list)
    action: dict | None = None         # 화면에 시키는 일 (예: 오른쪽 패널에 시험 화면)


def reply_full(db: Session, user: m.User, text: str, project: m.Project | None,
               files: list[Attachment] | None = None, session: m.ChatSession | None = None,
               quote: str | None = None, should_stop=lambda: False) -> Reply:
    """대화 답변 하나. 무엇을 할지는 이전 대화·학습 현황과 함께 판단한다 (services/intent.py).
    - 문제 요청 → 새 문제 (실패하면 문제 은행) · 계산·설명 → 풀이 · 현황 보고·일반 질문·되묻기 → 글로 답
    - 사진·PDF 를 첨부했으면 그 자료를 읽고 풀이로 답한다 (AI 가 있어야 함).
    should_stop: 비싼 단계 앞에서 확인 — 참이면 Stopped (학생이 멈추기를 눌렀다)."""
    def checkpoint():
        if should_stop():
            raise Stopped

    llm = get_llm()
    if files:
        checkpoint()
        return _files_reply(db, llm, user, text, files)
    if quote:
        checkpoint()
        return _deep_reply(db, llm, user, text, quote, session, project)
    has_history = bool(session and session.messages)
    if intent.fast_route(text, has_history) == "exam_mode":  # 시험 모드는 AI 없이 — 한도·AI 꺼짐과 상관없이
        return exam_reply(db, user, project, session)
    if llm and (why := quota.reason(db, user)):  # 한도를 넘으면 AI 없이 문제 은행에서
        ids = _from_bank(db, user, text, detect_domain(text), None)
        return Reply((f"{why.split('.')[0]}. 대신 문제 은행의 검증된 문제 {len(ids)}개를 보여드려요."
                      if ids else why), ids, intent="quota")
    if llm is None:  # AI 가 없으면 문제 은행에서
        return Reply(*reply(db, user, text, project), intent="make_problems")

    kind, request = intent.fast_route(text, has_history), text
    if kind is None:
        try:
            r = intent.route(db, llm, user, text, history=intent.history_text(db, user, session),
                             facts=intent.facts_text(db, user, project))
        except LLMError as e:
            # 판단을 못 하면 예전처럼 글자 기준으로 (계산 질문이면 풀이, 아니면 문제)
            log.warning("대화 의도 판단 실패: %s", e)
            kind = "explain" if explain.is_explain_request(text) else "make_problems"
        else:
            kind, request = r.intent, (r.request.strip() or text)
            if kind == "exam_mode":
                return exam_reply(db, user, project, session)
            if kind in ("project_report", "answer", "clarify"):
                return Reply(r.reply.strip() or "무엇을 도와드릴까요?", intent=kind, suggestions=r.suggestions)

    checkpoint()  # 문제 만들기·풀이는 오래 걸리고 비싸다 — 그 전에 멈췄는지 본다
    if kind == "explain":
        try:
            line, payload = explain.explain(db, llm, user, request, prompt=f"학생 질문: {request}" if request != text else None)
            return Reply(line, explanation=payload, intent="explain")
        except LLMError as e:
            log.warning("AI 풀이 실패: %s", e)
    return Reply(*reply(db, user, request, project), intent="make_problems")


EXAM_MAX = 40  # 대화 문제로 보는 시험의 최대 문항 수


def exam_reply(db: Session, user: m.User, project: m.Project | None, session: m.ChatSession | None) -> Reply:
    """시험 모드: 프로젝트에 올린 기출 문항이 있으면 그걸로, 없으면 이 대화에서 나온 문제로 오른쪽 패널에 시험 화면을 연다.
    AI 는 부르지 않는다."""
    if project is not None:
        n = len(project_past_problems(db, user, project))
        if n:
            return Reply(f"오른쪽에 '{project.name}' 기출 {n}문항으로 시험 화면을 열었어요. 타이머가 켜져 있고, 제출하면 바로 채점해요.",
                         intent="exam_mode", action={"type": "exam", "source": "project", "count": n},
                         suggestions=["틀린 문항 다시 풀기", "약점 개념 설명해줘"])
    seen: list[str] = []
    for x in (session.messages if session else []):
        for pid in x.problem_ids or []:
            if pid not in seen:
                seen.append(pid)
    if seen:
        n = min(len(seen), EXAM_MAX)
        return Reply(f"오른쪽에 이 대화에서 나온 {n}문제로 시험 화면을 열었어요. 제출하면 바로 채점하고, 틀린 문제는 오답노트에 담겨요.",
                     intent="exam_mode", action={"type": "exam", "source": "chat", "count": n},
                     suggestions=["비슷한 문제 5개 더 내줘", "틀린 문제 다시 설명해줘"])
    where = "이 프로젝트에 올린 기출이나 " if project is not None else ""
    return Reply(f"시험 볼 문항이 아직 없어요. {where}이 대화에서 문제를 먼저 만들면 바로 시험 모드로 풀 수 있어요.",
                 intent="exam_mode", suggestions=["5문제 내줘", "기출 올리는 방법 알려줘"])


def _deep_reply(db: Session, llm, user: m.User, text: str, quote: str, session: m.ChatSession | None,
                project: m.Project | None) -> Reply:
    """답글: 앞 답변에서 고른 부분을 이전 대화·학습 현황과 함께 더 깊고 자세하게 풀어 준다 (판단 없이 바로 풀이 모델)."""
    if llm is None:
        return Reply("고른 부분을 자세히 풀어 드리려면 AI 가 켜져 있어야 해요.", intent="deep")
    if why := quota.reason(db, user):
        return Reply(why, intent="quota")
    prompt = intent.deep_prompt(db, user, text=text, quote=quote, session=session, project=project)
    try:
        line, payload = explain.explain(db, llm, user, text, prompt=prompt, instructions=explain.DEEP_INSTRUCTIONS, purpose="deep")
    except LLMError as e:
        log.warning("답글 풀이 실패: %s", e)
        return Reply("고른 부분을 풀어 드리지 못했어요. 잠시 후 다시 보내 주세요.", intent="deep")
    return Reply(line.replace("풀이를 정리", "고른 부분을 더 자세히 정리", 1), explanation=payload, intent="deep")


def _files_reply(db: Session, llm, user: m.User, text: str, files: list[Attachment]) -> Reply:
    """첨부한 사진·PDF 를 읽고 풀이로 답한다. AI 가 없거나 한도를 넘었으면 이유를 알린다."""
    if llm is None:
        return Reply("사진·파일을 읽으려면 AI 가 켜져 있어야 해요. 지금은 문제를 글로 적어서 물어봐 주세요.", intent="explain_file")
    if why := quota.reason(db, user):
        return Reply(why, intent="quota")
    names = ", ".join(f.filename for f in files)
    prompt = f"학생 질문: {text}\n\n[첨부한 자료] {names}"
    try:
        line, payload = explain.explain(db, llm, user, text, prompt=prompt, instructions=explain.FILE_INSTRUCTIONS,
                                        purpose="explain_file", files=files)
    except LLMError as e:
        log.warning("첨부 자료 풀이 실패: %s", e)
        return Reply("첨부한 자료를 읽지 못했어요. 잠시 후 다시 보내 주거나, 더 선명한 사진으로 올려 주세요.", intent="explain_file")
    return Reply(line.replace("풀이를 정리", "첨부한 자료를 읽고 풀이를 정리", 1), explanation=payload, intent="explain_file")


def reply(db: Session, user: m.User, text: str, project: m.Project | None) -> tuple[str, list[str]]:
    """(답변 문장, 문제 id 목록)"""
    project_domain = db.get(m.Concept, project.subject_id).domain if project else None
    domain = detect_domain(text, project_domain)
    project_scope = (project.unit_ids or [project.subject_id]) if project else None
    scope = generator.resolve_scope(db, text, project_scope)  # 문장의 과목·단원 이름 > 프로젝트 범위

    llm = get_llm()
    note = ""
    if llm:
        plan = generator.plan_request(db, text, user=user, domain=domain, scope_ids=project_scope, max_count=MAX_PROBLEMS)
        if plan:
            # 프로젝트에 올린 기출 중 같은 개념의 문제가 있으면 본보기로 쓴다
            exemplars = project_past_problems(db, user, project, plan.concept_id) if project else []
            try:
                report = generator.generate_problems(
                    db, llm, concept_id=plan.concept_id, difficulty=plan.difficulty, count=plan.count, user=user,
                    question_type=project.question_type if project else "multiple_choice",
                    exemplars=exemplars, owner=user if exemplars else None,
                    textbook=textbook_label(project) if project else None)
            except (LLMError, ValueError) as e:
                log.warning("AI 문제 생성 실패: %s", e)
                report = None
            if report and report.accepted:
                concept = db.get(m.Concept, plan.concept_id)
                dropped = f" 검산에서 떨어진 {len(report.rejected)}문제는 뺐어요." if report.rejected else ""
                return (f"'{concept.name}' 문제 {len(report.accepted)}개를 만들고 한 번 더 풀어 검산했어요.{dropped} "
                        "틀린 문제는 오답노트에 저절로 담겨요.", report.accepted)
            note = "새로 만든 문제가 검산을 통과하지 못해서, "
        else:
            note = "어떤 개념인지 알아듣지 못해서, "

    ids = _from_bank(db, user, text, domain, scope)
    if not ids:
        where = f"'{db.get(m.Concept, scope[0]).name}' " if scope and len(scope) == 1 else "이 범위의 "
        return f"문제 은행에 아직 {where}문제가 없어요. 잠시 후 다시 요청하거나 개념을 구체적으로 말해 주세요 (예: 치환적분 3문제).", []
    prefix = note or "지금은 "
    return f"{prefix}검증된 문제 은행에서 {len(ids)}개를 골라 드려요. 틀린 문제는 오답노트에 저절로 담겨요.", ids
