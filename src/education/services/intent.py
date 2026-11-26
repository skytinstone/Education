"""대화 의도 판단 — 학생 메시지를 이전 대화·학습 현황과 함께 보고 무엇을 할지 정한다.

- 명확한 요청('치환적분 3문제', 식이 들어간 계산 질문)은 AI 를 부르지 않고 바로 정한다 (빠르고 싸다).
- 나머지는 가벼운 모델이 한 번 판단한다. 현황 보고·일반 질문·되묻기는 그 한 번의 호출로 답까지 만든다.
- 숫자(D-day·정답률·약점 등)는 DB 에서 뽑아 넘기고, AI 는 그 숫자만 써서 문장으로 정리한다.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.harness import prompts
from education.config import get_settings
from education.db import models as m
from education.services import explain, learning
from education.services.llm import LLM, LLMError

Intent = Literal["make_problems", "explain", "project_report", "exam_mode", "answer", "clarify"]
HISTORY_TURNS = 8  # 판단에 넘기는 최근 메시지 수

# 시험 모드(화면에서 시험 보기)로 들어가자는 요청 — 오른쪽 패널에 시험 화면을 연다
_EXAM_MODE = re.compile(r"시험\s*모드|모의\s*시험\s*(을|를)?\s*(시작|보|볼|쳐|치)|시험\s*(을|를)?\s*(보|쳐|치)(자|고\s*싶|게|기|러|\s*볼)|시험\s*(시작|진입)")
# 문제를 '내 달라는' 것이 분명한 요청 — '치환적분 3문제', '3문제 내줘', '문제 좀 만들어 줘'.
# '시험에 50문제가 나와요' 처럼 개수를 말하기만 한 문장은 요청이 아니므로 AI 판단으로 보낸다
_FAST_PROBLEM = re.compile(r"\d+\s*(문제|문항)\s*(씩|만|더)?\s*(내|만들|출제|줘|주세요|부탁|풀(어|고|래|자|게)|[.!?~]*$)"
                           r"|문제\s*(를|좀|하나)?\s*(내|만들|출제)")
# 식이 들어간 계산 질문 — 글자만으로 '극한·미분' 을 말한 질문은 맥락을 봐야 해서 AI 판단으로 보낸다
_FORMULA = re.compile(r"[∫√π^=²³]|\d\s*[x×*/+\-]|\b[a-z]\s*\(|\bx\b|lim|sin|cos|tan|log|ln")
# 앞 대화를 가리키는 말 — 있으면 글자만으로 정하지 않는다
_FOLLOW_UP = re.compile(r"아까|방금|이전|위\s*(에|의)|[그이저]\s*(문제|거|것)|(^|\s)더(\s|$)|다시|비슷|\d+\s*번")


def fast_route(text: str, has_history: bool) -> Intent | None:
    """AI 없이 정할 수 있으면 그 의도, 아니면 None."""
    t = text.strip()
    if _EXAM_MODE.search(t):
        return "exam_mode"
    if has_history and _FOLLOW_UP.search(t):
        return None
    if _FAST_PROBLEM.search(t):
        return "make_problems"
    if explain.is_explain_request(t) and _FORMULA.search(t):
        return "explain"
    return None


# ---------- AI 판단 ----------
class Route(BaseModel):
    intent: Intent = Field(description="학생의 마지막 메시지가 원하는 것")
    request: str = Field(description="make_problems·explain 일 때: 이전 대화를 반영해 이 문장만 읽어도 알 수 있게 다시 쓴 요청. 그 밖에는 빈 문자열")
    reply: str = Field(description="project_report·answer·clarify 일 때 학생에게 보일 답. make_problems·explain 이면 빈 문자열")
    suggestions: list[str] = Field(description="학생이 바로 이어서 보낼 만한 짧은 요청 0~3개")


INSTRUCTIONS = prompts.text("intent.instructions")  # harness/prompts/intent/instructions.md


def route(db: Session, llm: LLM, user: m.User, text: str, *, history: str, facts: str) -> Route:
    """AI 판단 한 번. 실패하면 LLMError — 호출한 쪽이 글자 기준으로 대신 정한다."""
    s = get_settings()
    nl = "\n"
    prompt = (f"[학습 현황]{nl}{facts}{nl}{nl}[이전 대화]{nl}{history or '(없음 — 새 대화)'}{nl}{nl}"
              f"[학생의 마지막 메시지]{nl}{text}")
    try:
        res = llm.structured(model=s.openai_model_route, effort=s.openai_effort_route, instructions=INSTRUCTIONS,
                             prompt=prompt, schema=Route, max_output_tokens=4000)
    except LLMError as e:
        db.add(m.LLMCall(purpose="route", model=s.openai_model_route, ok=False, error=str(e), user_id=user.id))
        db.flush()
        raise
    u = res.usage
    db.add(m.LLMCall(purpose="route", model=u.model, ok=True, user_id=user.id, cost_usd=u.cost_usd,
                     input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                     reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))
    db.flush()
    if not isinstance(res.data, Route):
        raise LLMError("판단 결과 형식이 달라요")
    r = res.data
    r.suggestions = [x.strip()[:60] for x in r.suggestions if x.strip()][:3]
    return r


# ---------- 맥락 ----------
def _short(text: str, n: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def history_text(db: Session, user: m.User, session: m.ChatSession | None) -> str:
    """최근 대화 — 답변에 나온 문제는 번호·개념·문제 앞부분·푼 결과까지 (학생이 '2번' 처럼 가리킬 수 있게)."""
    if session is None:
        return ""
    msgs = list(session.messages)[-HISTORY_TURNS:]
    ids = [pid for x in msgs for pid in (x.problem_ids or [])]
    problems = {p.id: p for p in db.scalars(select(m.Problem).where(m.Problem.id.in_(ids)))} if ids else {}
    results: dict[str, bool] = {}
    if ids:
        for pid, ok in db.execute(select(m.Attempt.problem_id, m.Attempt.correct)
                                  .where(m.Attempt.user_id == user.id, m.Attempt.problem_id.in_(ids))
                                  .order_by(m.Attempt.created_at)):
            results[pid] = ok
    lines = []
    for x in msgs:
        if x.role == "user":
            lines.append(f"학생: {_short(x.text, 300)}")
            continue
        lines.append(f"Eureka: {_short(x.text, 400)}")
        if x.explanation:
            lines.append(f"  (풀이) {_short(x.explanation.get('summary', ''), 200)}")
        for i, pid in enumerate(x.problem_ids or [], 1):
            p = problems.get(pid)
            if p is None:
                continue
            done = {True: " → 맞힘", False: " → 틀림"}.get(results.get(pid), " → 아직 안 풂")
            lines.append(f"  {i}번 문제: {_short(p.stem, 160)}{done}")
    return "\n".join(lines)


QTYPE = {"auto": "자동", "multiple_choice": "객관식", "short_answer": "단답형", "text": "주관식", "numeric": "수치형",
         "essay": "서술형", "mixed": "섞어서"}


def _pct(v: float | None) -> str:
    return f"{round(v * 100)}%" if v is not None else "아직 없음"


def facts_text(db: Session, user: m.User, project: m.Project | None) -> str:
    """판단·보고에 쓸 학습 현황 — 모두 DB 에서 센 값."""
    today = learning.local_today(db)
    lines = [f"오늘 날짜: {today.isoformat()}", f"오늘 푼 문제: {learning.today_count(db, user)}개",
             f"연속 학습: {learning.streak(db, user)}일"]
    if project is None:
        attempts = db.scalar(select(func.count()).where(m.Attempt.user_id == user.id))
        lines += ["선택한 프로젝트: 없음", f"지금까지 푼 문제: {attempts}개", f"전체 정답률: {_pct(learning.accuracy(db, user))}"]
        weak = learning.concept_stats(db, user)[:3]
        if weak:
            lines.append("약점 개념: " + ", ".join(f"{w.name} (정답률 {_pct(w.accuracy)}, {w.attempts}문제)" for w in weak))
        projects = list(db.scalars(select(m.Project).where(m.Project.user_id == user.id).order_by(m.Project.created_at)))
        if projects:
            lines.append("내 프로젝트: " + ", ".join(
                p.name + (f" (D-{(p.exam_date - today).days})" if p.exam_date and p.exam_date >= today else "") for p in projects))
        return "\n".join(lines)

    subject = db.get(m.Concept, project.subject_id)
    units = [c.name for c in db.scalars(select(m.Concept).where(m.Concept.id.in_(project.unit_ids)))] if project.unit_ids else []
    if units:
        scope = ", ".join(units)
    else:  # 과목 전체 — 어떤 단원이 들어 있는지도 알려 준다
        all_units = list(db.scalars(select(m.Concept.name).where(m.Concept.parent_id == project.subject_id).limit(30)))
        scope = f"과목 전체 (단원: {', '.join(all_units)})" if all_units else "과목 전체"
    lines += [f"프로젝트: {project.name}", f"과목: {subject.name if subject else project.subject_id}", f"학습 범위: {scope}"]
    if project.goal:
        lines.append(f"목표: {project.goal}")
    if project.textbook:
        lines.append(f"교재: {project.textbook}")
    lines.append(f"문제 형식: {QTYPE.get(project.question_type, project.question_type)}")
    if project.exam_date:
        left = (project.exam_date - today).days
        when = f"D-{left}" if left > 0 else "오늘" if left == 0 else f"{-left}일 지남"
        lines.append(f"시험일: {project.exam_date.isoformat()} ({when})")
    else:
        lines.append("시험일: 정하지 않음")
    attempts = db.scalar(select(func.count()).where(m.Attempt.user_id == user.id, m.Attempt.project_id == project.id))
    open_notes = db.scalar(select(func.count()).where(
        m.WrongNote.user_id == user.id, m.WrongNote.project_id == project.id, m.WrongNote.resolved_at.is_(None)))
    lines += [f"이 프로젝트에서 푼 문제: {attempts}개", f"정답률: {_pct(learning.accuracy(db, user, project_id=project.id))}",
              f"남은 오답: {open_notes}개"]
    weak = learning.concept_stats(db, user, project_id=project.id)[:3]
    lines.append("약점 개념: " + (", ".join(f"{w.name} (정답률 {_pct(w.accuracy)}, {w.attempts}문제)" for w in weak) if weak else "아직 없음"))
    mats = db.execute(select(func.count(), func.coalesce(func.sum(m.Material.problem_count), 0))
                      .where(m.Material.project_id == project.id, m.Material.kind != "answer_sheet")).one()
    lines.append(f"올린 기출·자료: {mats[0]}개 (문항 {mats[1]}개)")
    exams = list(db.scalars(select(m.ExamRecord).where(m.ExamRecord.user_id == user.id, m.ExamRecord.project_id == project.id)
                            .order_by(m.ExamRecord.created_at.desc()).limit(3)))
    if exams:
        lines.append("최근 시험: " + ", ".join(
            f"{e.created_at.date().isoformat()} {e.correct}/{e.total} 정답 ({e.score}/{e.total_points}점)" for e in exams))
    else:
        lines.append("최근 시험: 아직 없음")
    return "\n".join(lines)


def deep_prompt(db: Session, user: m.User, *, text: str, quote: str, session: m.ChatSession | None,
                project: m.Project | None) -> str:
    """답글(인용해서 더 깊게 묻기)에 넘길 자료 — 학습 현황·이전 대화·인용한 부분·질문."""
    nl = "\n"
    parts = []
    if project is not None:
        parts.append(f"[학습 현황]{nl}{facts_text(db, user, project)}")
    if hist := history_text(db, user, session):
        parts.append(f"[이전 대화]{nl}{hist}")
    parts += [f"[인용한 부분]{nl}{quote}", f"[학생 질문]{nl}{text}"]
    return (nl * 2).join(parts)
