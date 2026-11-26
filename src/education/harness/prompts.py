"""프롬프트 레지스트리 — AI 에게 주는 지시문을 코드 밖 파일(harness/prompts/<모듈>/<이름>.md)로 두고 버전을 매긴다.

- 버전은 지시문 내용의 해시 앞 8자리다. 글자 하나만 바뀌어도 버전이 바뀌므로 '언제 무엇을 바꿨는지' 를 따로 적지 않아도
  실행 기록(agent_runs)에 남은 버전으로 어떤 지시문이 쓰였는지 정확히 알 수 있다
- harness_version(): 모든 지시문 버전과 모델 설정을 합친 하네스 전체의 버전 — 평가 점수를 버전끼리 비교할 때 쓴다
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from education.config import get_settings

ROOT = Path(__file__).parent / "prompts"


@lru_cache
def text(name: str) -> str:
    """예: text('generator.generator_instructions') → prompts/generator/generator_instructions.md"""
    module, key = name.split(".", 1)
    # 줄바꿈은 LF 로 (Windows 에서 CRLF 로 받아도 지시문과 버전이 같게)
    return (ROOT / module / f"{key}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def version(name: str) -> str:
    return hashlib.sha256(text(name).encode()).hexdigest()[:8]


def names() -> list[str]:
    return sorted(f"{p.parent.name}.{p.stem}" for p in ROOT.glob("*/*.md"))


def versions() -> dict[str, str]:
    return {n: version(n) for n in names()}


def models() -> dict[str, str]:
    s = get_settings()
    return {"generate": f"{s.openai_model_generate}/{s.openai_effort_generate}",
            "verify": f"{s.openai_model_verify}/{s.openai_effort_verify}",
            "route": f"{s.openai_model_route}/{s.openai_effort_route}",
            "chat": f"{s.openai_model_chat}/{s.openai_effort_chat}",
            "embedding": s.embedding_model,
            "self_correct": str(s.ai_self_correct), "tool_check": str(s.ai_tool_check)}


def harness_version() -> str:
    raw = "|".join(f"{k}={v}" for k, v in sorted({**versions(), **models()}.items()))
    return hashlib.sha256(raw.encode()).hexdigest()[:8]
