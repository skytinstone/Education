"""문제 Deep Dive — 틀린(또는 찍어서 맞힌) 문제를 작은 질문 3~5개로 쪼개 한 단계씩 다시 따라간다.

- 내가 낸 답을 보고 '어디서 갈라졌는지' 진단부터 한다 → 사람마다 따로 만든다 (사용자 × 문제 하나)
- 단계마다 보기를 고르면 바로 맞았는지, 틀리면 힌트를 준다. 마지막 단계의 답은 문제의 정답과 같아야 한다
- 끝나면 '이해했어요 / 아직 헷갈려요' 피드백을 받는다. 헷갈리면 더 잘게 쪼개 다시 만들고,
  그 피드백은 학습 플래너가 그 개념의 우선순위를 올리는 데 쓴다 (services/planner.py)
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.harness import prompts
from education.config import get_settings
from education.db import models as m
from education.services.llm import LLM, LLMError
from education.services.solutions import _answer_text

MAX_ROUNDS = 3


class DeepDiveError(Exception):
    pass


class DiveStep(BaseModel):
    question: str = Field(description="이 단계에서 학생에게 묻는 짧은 질문. 인라인 수식은 $...$")
    choices: list[str] = Field(description="보기 3~4개 (인라인 수식은 $...$)")
    answer: int = Field(description="맞는 보기 번호 (1부터)")
    hint: str = Field(description="틀렸을 때 줄 힌트 한 문장 (답을 바로 말하지 않음)")
    explain: str = Field(description="맞힌 뒤 보여 줄 설명 한두 문장")


class Dive(BaseModel):
    diagnosis: str = Field(description="학생이 낸 답을 보고 어디서 갈라졌는지 진단 한두 문장 (맞힌 경우엔 핵심을 다시 짚는 말)")
    steps: list[DiveStep] = Field(description="문제를 푸는 순서대로 3~5단계. 마지막 단계는 최종 답을 고르는 질문")
    takeaway: str = Field(description="이 문제에서 꼭 가져갈 한 문장")


INSTRUCTIONS = prompts.text("deepdive.instructions")  # harness/prompts/deepdive/instructions.md


def get(db: Session, user: m.User, problem_id: str) -> m.DeepDive | None:
    return db.scalar(select(m.DeepDive).where(m.DeepDive.user_id == user.id, m.DeepDive.problem_id == problem_id))


def out(d: m.DeepDive) -> dict:
    return {"id": str(d.id), "problem_id": d.problem_id, **d.content, "answers": d.answers, "feedback": d.feedback,
            "rounds": d.rounds, "completed": d.completed_at is not None}


def _prompt(p: m.Problem, my_answer: str, correct: bool, simpler: bool) -> str:
    nl = "\n"
    parts = [f"[문제]{nl}{p.stem}"]
    if p.choices:
        parts.append("[보기]" + nl + nl.join(f"{i}. {c}" for i, c in enumerate(p.choices, 1)))
    parts.append(f"[정답]{nl}{_answer_text(p)}")
    if p.solution:
        parts.append(f"[해설]{nl}{p.solution}")
    shown = my_answer
    if p.choices and my_answer.isdigit() and 1 <= int(my_answer) <= len(p.choices):
        shown = f"{my_answer}번 ({p.choices[int(my_answer) - 1]})"
    parts.append(f"[학생이 낸 답]{nl}{shown} — {'맞힘' if correct else '틀림'}")
    if simpler:
        parts.append("[요청]\n학생이 지난번 단계 풀이를 보고도 아직 헷갈린다고 했어요. 더 잘게, 더 쉽게 쪼개 주세요.")
    return (nl * 2).join(parts)


def _payload(res: Dive) -> dict:
    steps = []
    for st in res.steps[:5]:
        choices = [c for c in st.choices if c.strip()][:4]
        if len(choices) < 2 or not 1 <= st.answer <= len(choices):
            continue  # 정답 번호가 보기 밖이면 그 단계는 버린다
        steps.append({"question": st.question, "choices": choices, "answer": st.answer, "hint": st.hint, "explain": st.explain})
    if len(steps) < 2:
        raise DeepDiveError("단계를 제대로 나누지 못했어요")
    return {"diagnosis": res.diagnosis, "steps": steps, "takeaway": res.takeaway}


def create(db: Session, llm: LLM, user: m.User, p: m.Problem, *, retry: bool = False) -> m.DeepDive:
    """Deep Dive 를 만든다. 이미 있으면 그대로 — retry 면 '더 잘게' 다시 만든다 (최대 MAX_ROUNDS 번)."""
    dive = get(db, user, p.id)
    if dive is not None and not retry:
        return dive
    if dive is not None and dive.rounds >= MAX_ROUNDS:
        raise DeepDiveError(f"Deep Dive 는 한 문제에 {MAX_ROUNDS}번까지 다시 만들 수 있어요")
    last = db.scalar(select(m.Attempt).where(m.Attempt.user_id == user.id, m.Attempt.problem_id == p.id)
                     .order_by(m.Attempt.created_at.desc()).limit(1))
    s = get_settings()
    try:
        res = llm.structured(model=s.openai_model_generate, effort=s.openai_effort_generate, instructions=INSTRUCTIONS,
                             prompt=_prompt(p, last.answer if last else "", bool(last and last.correct), dive is not None),
                             schema=Dive, max_output_tokens=10000)
    except LLMError as e:
        db.add(m.LLMCall(purpose="deep_dive", model=s.openai_model_generate, ok=False, error=str(e), user_id=user.id))
        db.flush()
        raise DeepDiveError(str(e)) from None
    u = res.usage
    db.add(m.LLMCall(purpose="deep_dive", model=u.model, ok=True, user_id=user.id, cost_usd=u.cost_usd,
                     input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                     reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))
    db.flush()
    content = _payload(res.data)
    if dive is None:
        dive = m.DeepDive(user_id=user.id, problem_id=p.id, content=content, answers=[])
        db.add(dive)
    else:  # 더 잘게 다시 — 이전 답과 피드백은 비운다
        dive.content, dive.answers, dive.feedback, dive.completed_at = content, [], None, None
        dive.rounds += 1
    db.flush()
    return dive


def save(db: Session, dive: m.DeepDive, answers: list[int] | None, feedback: str | None) -> m.DeepDive:
    """단계마다 처음 고른 보기와 마지막 피드백을 저장한다. 피드백을 남기면 끝난 것으로 친다."""
    n = len(dive.content.get("steps", []))
    if answers is not None:
        dive.answers = [int(a) for a in answers[:n]]
    if feedback is not None:
        dive.feedback = feedback
        dive.completed_at = func.now()
    db.flush()
    db.refresh(dive)
    return dive
