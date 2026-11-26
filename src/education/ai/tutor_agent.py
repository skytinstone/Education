"""대화 에이전트 (LangChain create_agent · Tool Calling · RAG) — '현황·상담' 질문에 도구를 골라 쓰며 답한다.

지금까지는 학습 현황을 통째로 미리 넣고 한 번에 답했다. 에이전트는 필요한 것만 도구로 찾아본다.

    get_study_status  프로젝트(시험) 현황 — D-day · 정답률 · 남은 오답 · 약점 · 최근 시험
    get_today_plan    학습 플래너의 오늘 할 일과 진행도 · AI 계획 검토 요약
    get_wrong_notes   아직 못 푼 오답 (개념 · 문제 앞부분)
    search_problems   요청과 비슷한 검증된 문제 검색 (RAG · pgvector)
    + 계산 도구       (ai/sympy_tools.py)

데이터를 바꾸는 일(문제 만들기 · 시험 시작)은 에이전트가 직접 하지 않는다. 답과 함께 '다음에 보낼 요청'(suggestions)이나
start_exam 을 돌려주면, 화면이 버튼으로 보여 주고 학생이 눌렀을 때만 기존 경로가 실행된다 (사람이 확인하는 단계).

도구는 RuntimeContext 의 사용자 범위 안에서만 동작한다. LangGraph 가 도구를 동시에 부를 수 있어 DB 세션은 잠금으로 보호한다.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from education.harness import prompts
from education.ai import models, rag
from education.ai.sympy_tools import MATH_TOOLS
from education.config import get_settings
from education.db import models as m
from education.services import intent, planner
from education.services.llm import LLMError, Usage

MAX_STEPS = 12


@dataclass
class Ctx:
    db: Session
    user: m.User
    project: m.Project | None
    lock: threading.Lock = field(default_factory=threading.Lock)
    used: list[str] = field(default_factory=list)  # 부른 도구 (기록용)


class AgentReply(BaseModel):
    reply: str = Field(description="학생에게 보일 답 (해요체, 첫 줄에 질문에 대한 직접적인 답). 학생 기록의 숫자는 도구 결과에 있는 것만")
    suggestions: list[str] = Field(description="학생이 바로 이어서 보낼 요청 0~3개 (실제로 보낼 문장, 각 20자 안쪽). 예: '열역학 3문제 내줘'")
    start_exam: bool = Field(description="학생이 지금 시험(모의시험)을 보겠다고 했을 때만 true")


INSTRUCTIONS = prompts.text("tutor_agent.instructions")  # harness/prompts/tutor_agent/instructions.md


def _ctx(runtime: ToolRuntime) -> Ctx:
    return runtime.context


@tool
def get_study_status(runtime: ToolRuntime[Ctx]) -> str:
    """지금 학생의 학습 현황: 오늘 푼 문제 · 연속 학습 · (선택한 프로젝트가 있으면) 시험일 · 정답률 · 남은 오답 · 약점 개념 · 최근 시험."""
    c = _ctx(runtime)
    with c.lock:
        c.used.append("get_study_status")
        return intent.facts_text(c.db, c.user, c.project)


@tool
def get_today_plan(runtime: ToolRuntime[Ctx]) -> str:
    """학습 플래너의 오늘 할 일(진행도 포함)과 남은 기간 · 범위 커버 · AI 계획 검토 요약. 시험일이 가장 가까운 프로젝트 기준."""
    c = _ctx(runtime)
    with c.lock:
        c.used.append("get_today_plan")
        project = c.project or _nearest_project(c.db, c.user)
        if project is None:
            return "시험 프로젝트가 없어요. 프로젝트를 만들면 플래너가 오늘 할 일을 정해 줘요."
        v = planner.view(c.db, c.user, project)
        s = v["summary"]
        lines = [f"프로젝트: {project.name} · " + (f"D-{v['days_left']}" if v["days_left"] is not None else "시험일 미정"),
                 f"범위 개념 {s['concepts']}개 중 {s['touched']}개 풀어 봄 · 약점 {s['weak']} · 남은 오답 {s['open_notes']}",
                 "오늘 할 일:"]
        lines += [f"• {t['title']} ({t['progress']}/{t['target']}{' 완료' if t['done'] else ''})" for t in v["tasks"]] or ["• 없음"]
        if v["review"]:
            lines.append(f"AI 계획 검토: {v['review']['headline']}")
        return "\n".join(lines)


@tool
def get_wrong_notes(runtime: ToolRuntime[Ctx], limit: int = 5) -> str:
    """아직 다시 풀어 맞히지 못한 오답 (최근 순). 개념 이름과 문제 앞부분."""
    c = _ctx(runtime)
    with c.lock:
        c.used.append("get_wrong_notes")
        rows = c.db.execute(
            select(m.Problem.stem, m.Concept.name, m.WrongNote.error_type)
            .join(m.Problem, m.Problem.id == m.WrongNote.problem_id)
            .outerjoin(m.ProblemConcept, m.ProblemConcept.problem_id == m.Problem.id)
            .outerjoin(m.Concept, m.Concept.id == m.ProblemConcept.concept_id)
            .where(m.WrongNote.user_id == c.user.id, m.WrongNote.resolved_at.is_(None))
            .order_by(m.WrongNote.created_at.desc()).limit(max(1, min(limit, 10)))).all()
        if not rows:
            return "남은 오답이 없어요."
        return "\n".join(f"• [{name or '개념 없음'}] {stem[:80]} (틀린 이유: {err})" for stem, name, err in rows)


@tool
def search_problems(query: str, runtime: ToolRuntime[Ctx], k: int = 3) -> str:
    """요청과 의미가 비슷한 검증된 문제를 찾는다 (RAG). 예: query='치환적분 함정이 있는 정적분'."""
    c = _ctx(runtime)
    with c.lock:
        c.used.append("search_problems")
        hits = rag.search(c.db, c.user, query, k=max(1, min(k, 5)))
        if not hits:
            return "비슷한 문제를 찾지 못했어요."
        return "\n".join(f"• ({h.similarity:.2f}) {h.problem.stem[:100]}" for h in hits)


@tool
def get_past_exams(runtime: ToolRuntime[Ctx], year: str = "") -> str:
    """학생이 프로젝트에 올린 기출 자료와 거기서 뽑은 문제 전체 (자료 이름 · 문제 형식 · 개념 · 문제 앞부분).
    기출 유형 분석 · 연도별 출제 경향 · 자주 나온 개념 질문에 쓴다. year 를 주면 자료 이름에 그 글자가 든 것만 (예: '2024')."""
    c = _ctx(runtime)
    with c.lock:
        c.used.append("get_past_exams")
        project = c.project or _nearest_project(c.db, c.user)
        if project is None:
            return "시험 프로젝트가 없어요."
        mats = [x for x in c.db.scalars(select(m.Material).where(m.Material.project_id == project.id,
                                                                   m.Material.kind == "past_exam")
                                        .order_by(m.Material.filename))
                if not year or year in x.filename]
        if not mats:
            return f"프로젝트 '{project.name}' 에 {'이름에 ' + repr(year) + ' 이 든 ' if year else ''}기출 자료가 없어요."
        rows = c.db.execute(
            select(m.Problem.material_id, m.Problem.problem_type, m.Problem.stem, m.Concept.name)
            .outerjoin(m.ProblemConcept, m.ProblemConcept.problem_id == m.Problem.id)
            .outerjoin(m.Concept, m.Concept.id == m.ProblemConcept.concept_id)
            .where(m.Problem.material_id.in_([x.id for x in mats]), m.Problem.owner_user_id == c.user.id)
            .order_by(m.Problem.material_id, m.Problem.created_at)).all()
        by_mat: dict = {}
        for mid, qtype, stem, concept in rows:
            by_mat.setdefault(mid, []).append(f"  - [{concept or '개념 미분류'} · {qtype}] {' '.join(stem.split())[:110]}")
        out, budget = [f"프로젝트: {project.name} · 기출 자료 {len(mats)}개 · 문제 {len(rows)}개"], PAST_EXAM_LINES
        for x in mats:
            items = by_mat.get(x.id, [])
            out.append(f"• {x.filename} — 문제 {len(items)}개" + ("" if x.status == "ready" else f" (상태: {x.status})"))
            out += items[:budget]
            budget = max(0, budget - len(items))
        if len(rows) > PAST_EXAM_LINES:
            out.append("(문제가 많아 일부만 보였어요 — year 로 좁혀 다시 부를 수 있어요)")
        return "\n".join(out)


PAST_EXAM_LINES = 80  # 한 번에 넘기는 기출 문제 줄 수 (토큰 비용 상한)


def _nearest_project(db: Session, user: m.User) -> m.Project | None:
    from education.services import learning
    today = learning.local_today(db)
    ps = list(db.scalars(select(m.Project).where(m.Project.user_id == user.id)))
    soon = sorted((p for p in ps if p.exam_date and p.exam_date >= today), key=lambda p: p.exam_date)
    return soon[0] if soon else (max(ps, key=lambda p: p.created_at) if ps else None)


TOOLS = [get_study_status, get_today_plan, get_wrong_notes, get_past_exams, search_problems, *MATH_TOOLS]


def enabled() -> bool:
    s = get_settings()
    return s.ai_chat_agent and bool(s.openai_api_key)


def run(db: Session, user: m.User, project: m.Project | None, text: str, *, history: str = "") -> tuple[AgentReply, Usage, list]:
    """에이전트 한 번. 실패하면 LLMError (부르는 쪽은 기존 한 번 답으로 돌아간다)."""
    s = get_settings()
    model = models.get_chat_model(s.openai_model_chat, s.openai_effort_chat, max_tokens=6000)
    if model is None:
        raise LLMError("AI 가 설정되지 않았어요")
    ctx = Ctx(db=db, user=user, project=project)
    content = (f"[이전 대화]\n{history}\n\n" if history else "") + f"[학생의 마지막 메시지]\n{text}"
    started = time.monotonic()
    try:
        agent = create_agent(model, TOOLS, system_prompt=INSTRUCTIONS, response_format=ToolStrategy(AgentReply),
                             context_schema=Ctx, name="eureka_coach")
        res = agent.invoke({"messages": [{"role": "user", "content": content}]}, context=ctx,
                           config={"recursion_limit": MAX_STEPS})
    except Exception as e:
        raise LLMError(f"대화 에이전트 실패: {type(e).__name__}: {e}") from e
    out = res.get("structured_response")
    if not isinstance(out, AgentReply):
        raise LLMError("에이전트 답 형식이 달라요")
    out.suggestions = [x.strip()[:60] for x in out.suggestions if x.strip()][:3]
    return out, models.usage_of(res["messages"], s.openai_model_chat, started), res["messages"]
