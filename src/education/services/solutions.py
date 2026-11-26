"""한 문제를 푸는 여러 가지 방법 — '다른 풀이 보기'.

문제를 풀고 나면 정석 풀이 말고도 빠른 풀이, 그래프로 보는 풀이처럼 다른 길을 2~3가지 보여 준다.
- 정답은 문제에 이미 정해져 있다. AI 는 그 답에 이르는 서로 다른 방법만 쓰고, 답을 바꾸지 않는다
- 그래프 점은 서버가 계산한다 (explain._graph_payload — AI 가 찍은 좌표를 믿지 않음)
- 문제마다 한 번 만들어 저장하고, 그 문제를 볼 수 있는 사람이 같이 본다 (AI 는 문제당 한 번만 부른다)
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.harness import prompts
from education.config import get_settings
from education.db import models as m
from education.services.explain import Graph, Step, _graph_payload
from education.services.llm import LLM, LLMError

log = logging.getLogger(__name__)


class MethodsError(Exception):
    pass


class Method(BaseModel):
    name: str = Field(description="풀이 이름 (짧게), 예: '치환적분으로', '그래프 넓이로 보기', '보기를 대입해 빠르게'")
    when: str = Field(description="이 방법이 좋은 때를 한 문장으로. 인라인 수식은 $...$")
    summary: str = Field(description="이 방법의 핵심 아이디어 한두 문장. 인라인 수식은 $...$")
    steps: list[Step] = Field(description="2~6단계")
    result: str = Field(description="최종 답 (LaTeX, $ 없이). 반드시 주어진 정답과 같은 값")
    graph: Graph | None = Field(description="그래프로 보면 이해가 쉬운 방법이면 그래프, 아니면 null")


class Methods(BaseModel):
    methods: list[Method] = Field(description="서로 다른 풀이 2~3가지")


INSTRUCTIONS = prompts.text("solutions.instructions")  # harness/prompts/solutions/instructions.md


def get(db: Session, problem_id: str) -> dict | None:
    row = db.get(m.ProblemMethods, problem_id)
    return row.content if row else None


def _answer_text(p: m.Problem) -> str:
    if p.choices and p.answer.isdigit() and 1 <= int(p.answer) <= len(p.choices):
        return f"{p.answer}번 ({p.choices[int(p.answer) - 1]})"
    return p.answer


def _prompt(p: m.Problem) -> str:
    nl = "\n"
    parts = [f"[문제]{nl}{p.stem}"]
    if p.choices:
        parts.append("[보기]" + nl + nl.join(f"{i}. {c}" for i, c in enumerate(p.choices, 1)))
    parts.append(f"[정답]{nl}{_answer_text(p)}")
    if p.solution:
        parts.append(f"[기존 해설]{nl}{p.solution}")
    return (nl * 2).join(parts)


def _payload(res: Methods) -> dict:
    out = []
    for x in res.methods[:3]:
        if not x.steps:
            continue
        out.append({
            "name": x.name[:40], "when": x.when, "summary": x.summary,
            "steps": [st.model_dump() for st in x.steps[:6]], "result": x.result,
            "graph": _graph_payload(x.graph) if x.graph else None,
        })
    if len(out) < 2:
        raise MethodsError("서로 다른 풀이를 두 가지 이상 만들지 못했어요")
    return {"methods": out}


def create(db: Session, llm: LLM, user: m.User, p: m.Problem) -> dict:
    """여러 가지 풀이를 만들어 저장하고 돌려준다. 이미 있으면 그대로 돌려준다."""
    if (cached := get(db, p.id)) is not None:
        return cached
    s = get_settings()
    try:
        res = llm.structured(model=s.openai_model_generate, effort=s.openai_effort_generate, instructions=INSTRUCTIONS,
                             prompt=_prompt(p), schema=Methods, max_output_tokens=12000)
    except LLMError as e:
        db.add(m.LLMCall(purpose="methods", model=s.openai_model_generate, ok=False, error=str(e), user_id=user.id))
        db.flush()
        raise MethodsError(str(e)) from None
    u = res.usage
    db.add(m.LLMCall(purpose="methods", model=u.model, ok=True, user_id=user.id, cost_usd=u.cost_usd,
                     input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                     reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))
    db.flush()
    content = _payload(res.data)
    # 같은 문제를 두 사람이 동시에 열면 먼저 저장한 쪽을 쓴다
    db.execute(insert(m.ProblemMethods).values(problem_id=p.id, content=content).on_conflict_do_nothing())
    db.flush()
    return get(db, p.id) or content
