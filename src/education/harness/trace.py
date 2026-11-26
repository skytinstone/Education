"""실행 추적 — AI 실행 한 번을 단계별로 기록한다 (agent_runs).

    run = Trace("generate", prompts=["generator.generator_instructions", ...], user=user, input="치환적분 · 난이도 3")
    run.step("generate", model=..., usage=usage, data={...})      # 모델 호출
    run.step("tool:definite_integral", data={"args": ..., "result": ...})  # 도구 호출
    run.step("duplicate_check", ok=False, data={"similarity": 0.97})      # 검사
    run.save(db, status="rejected", output="중복", problem_id=pid)

- 단계마다 걸린 시간(직전 단계 이후 ms) · 모델 · 토큰 · 비용을 남기고, 전체 비용·시간을 합친다
- 하네스 버전(지시문 버전 + 모델 설정의 해시)과 이 실행에 쓴 지시문 버전을 함께 남긴다 → 같은 버전끼리 평가 비교
- 긴 값은 잘라서 저장한다 (학생 글·문제 본문은 앞부분만)
- 기록이 실패해도 본 기능은 멈추지 않는다
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from education.db import models as m
from education.harness import prompts
from education.services.llm import Usage

log = logging.getLogger(__name__)
MAX_TEXT = 600


def clip(v: Any, n: int = MAX_TEXT) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + "…"
    if isinstance(v, dict):
        return {k: clip(x, n) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clip(x, n) for x in list(v)[:30]]
    return v


class Trace:
    def __init__(self, kind: str, *, prompts_used: list[str], user: m.User | None = None, input: str = ""):
        self.kind, self.user, self.input = kind, user, input
        self.prompt_versions = {n: prompts.version(n) for n in prompts_used}
        self.steps: list[dict] = []
        self.started = self._last = time.monotonic()

    def step(self, name: str, *, ok: bool = True, model: str | None = None, usage: Usage | None = None,
             data: dict | None = None, error: str | None = None) -> None:
        now = time.monotonic()
        s: dict = {"name": name, "ok": ok and error is None, "ms": int((now - self._last) * 1000)}
        self._last = now
        if usage is not None:
            s.update(model=usage.model, tokens={"in": usage.input_tokens, "out": usage.output_tokens,
                                                 "reasoning": usage.reasoning_tokens}, cost=usage.cost_usd)
        elif model:
            s["model"] = model
        if data:
            s["data"] = clip(data)
        if error:
            s["error"] = clip(error, 300)
        self.steps.append(s)

    def tool_steps(self, messages) -> None:
        """LangChain 에이전트 메시지에서 도구 호출과 결과를 단계로 옮긴다 (구조화 응답용 가짜 도구는 뺀다)."""
        results = {getattr(msg, "tool_call_id", None): getattr(msg, "content", "") for msg in messages
                   if type(msg).__name__ == "ToolMessage"}
        for msg in messages:
            for c in getattr(msg, "tool_calls", None) or []:
                if c["name"][:1].isupper():  # MathCheck · AgentReply 같은 응답 형식
                    continue
                self.steps.append({"name": f"tool:{c['name']}", "ok": not str(results.get(c.get("id"), "")).startswith("오류"),
                                   "ms": 0, "data": clip({"args": c.get("args", {}), "result": results.get(c.get("id"), "")}, 300)})

    def save(self, db: Session, *, status: str, output: str = "", problem_id: str | None = None) -> m.AgentRun | None:
        try:
            costs = [s["cost"] for s in self.steps if s.get("cost") is not None]
            run = m.AgentRun(kind=self.kind, status=status, user_id=self.user.id if self.user else None, problem_id=problem_id,
                             harness_version=prompts.harness_version(), prompt_versions=self.prompt_versions,
                             input=clip(self.input), output=clip(output), steps=self.steps,
                             cost_usd=round(sum(costs), 6) if costs else None,
                             latency_ms=int((time.monotonic() - self.started) * 1000))
            with db.begin_nested():  # 실패하면 이 기록만 되돌린다
                db.add(run)
            return run
        except Exception as e:  # 기록 실패가 본 기능을 막지 않게
            log.warning("실행 기록 실패: %s", e)
            return None
