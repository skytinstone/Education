"""LLM 호출 — 모델 제공자를 이 파일 한 곳에 가둔다.

다른 제공자로 바꾸거나 비교 실험을 할 때는 LLM 프로토콜을 구현한 클래스를 하나 더 만들면 된다.
모든 호출은 토큰 사용량과 예상 비용을 함께 돌려주고, 호출한 쪽이 llm_calls 테이블에 기록한다.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import openai
from pydantic import BaseModel

from education.config import get_settings

T = TypeVar("T", bound=BaseModel)

# 100만 토큰당 (입력, 출력) USD — https://developers.openai.com/api/docs/models (2026-10 확인)
# 추론 토큰은 출력 요금으로 청구된다. 캐시된 입력 할인은 반영하지 않아 실제보다 약간 높게 잡힌다.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-astra": (10.0, 50.0),
    "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-luna": (0.10, 0.50),
}


@dataclass(frozen=True)
class Attachment:
    """함께 보낼 파일 — PDF 또는 이미지(png·jpeg·webp)."""
    data: bytes
    mime: str
    filename: str = "file"

    def to_input(self) -> dict:
        b64 = base64.b64encode(self.data).decode()
        if self.mime == "application/pdf":
            return {"type": "input_file", "filename": self.filename, "file_data": f"data:{self.mime};base64,{b64}"}
        return {"type": "input_image", "image_url": f"data:{self.mime};base64,{b64}", "detail": "high"}


class LLMError(Exception):
    """API 오류, 거절, 출력 잘림 등 — 호출한 쪽은 재시도하거나 대체 경로로 간다."""


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0

    @property
    def cost_usd(self) -> float | None:
        price = PRICES.get(self.model)
        if price is None:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000


@dataclass
class LLMResult(Generic[T]):
    data: T
    usage: Usage


class LLM(Protocol):
    def structured(self, *, model: str, effort: str, instructions: str, prompt: str, schema: type[T],
                   max_output_tokens: int = 16000, files: list[Attachment] | None = None) -> LLMResult[T]: ...


class OpenAILLM:
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key, timeout=180, max_retries=2)

    def structured(self, *, model: str, effort: str, instructions: str, prompt: str, schema: type[T],
                   max_output_tokens: int = 16000, files: list[Attachment] | None = None) -> LLMResult[T]:
        started = time.monotonic()
        content = prompt if not files else [
            {"role": "user", "content": [*(f.to_input() for f in files), {"type": "input_text", "text": prompt}]}]
        try:
            res = self.client.responses.parse(
                model=model, instructions=instructions, input=content, text_format=schema,
                reasoning={"effort": effort}, max_output_tokens=max_output_tokens, store=False,
            )
        except openai.APIError as e:
            raise LLMError(f"OpenAI 호출 실패: {type(e).__name__}: {e}") from e
        usage = Usage(model=model, latency_ms=int((time.monotonic() - started) * 1000))
        if res.usage:
            usage.input_tokens = res.usage.input_tokens
            usage.output_tokens = res.usage.output_tokens
            usage.cached_tokens = res.usage.input_tokens_details.cached_tokens or 0
            usage.reasoning_tokens = res.usage.output_tokens_details.reasoning_tokens or 0
        if res.output_parsed is None:  # 거절이거나 max_output_tokens 에 걸려 잘림
            raise LLMError(f"구조화된 응답을 받지 못했어요 (status={res.status})")
        return LLMResult(data=res.output_parsed, usage=usage)


def get_llm() -> LLM | None:
    key = get_settings().openai_api_key
    return OpenAILLM(key) if key else None
