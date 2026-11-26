"""LangChain 모델·임베딩 만들기와 토큰·비용 집계.

테스트는 get_chat_model · get_embedder 를 가짜로 바꿔 끼운다 (실제 API 를 부르지 않음).
"""

from __future__ import annotations

import time
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from education.config import get_settings
from education.services.llm import Usage

EMBED_DIM = 1536  # text-embedding-3-small 의 기본 차원 (DB 컬럼과 같아야 함)


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def get_chat_model(model: str, effort: str, max_tokens: int = 8000) -> BaseChatModel | None:
    """OpenAI 키가 없으면 None — 부르는 쪽은 도구 없는 기존 경로로 간다."""
    key = get_settings().openai_api_key
    if not key:
        return None
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model, api_key=key, reasoning_effort=effort, use_responses_api=True,
                      max_tokens=max_tokens, timeout=180, max_retries=2)


def get_embedder() -> Embedder | None:
    s = get_settings()
    if not s.openai_api_key:
        return None
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=s.embedding_model, dimensions=EMBED_DIM, api_key=s.openai_api_key)


def usage_of(messages: list[BaseMessage], model: str, started: float) -> Usage:
    """에이전트가 여러 번 부른 모델 호출의 토큰을 합친다 (usage_metadata)."""
    u = Usage(model=model, latency_ms=int((time.monotonic() - started) * 1000))
    for msg in messages:
        meta = getattr(msg, "usage_metadata", None) or {}
        u.input_tokens += meta.get("input_tokens", 0) or 0
        u.output_tokens += meta.get("output_tokens", 0) or 0
        u.cached_tokens += (meta.get("input_token_details") or {}).get("cache_read", 0) or 0
        u.reasoning_tokens += (meta.get("output_token_details") or {}).get("reasoning", 0) or 0
    return u


def token_count(texts: list[str]) -> int:
    """임베딩 비용 계산용 토큰 수 (임베딩 API 응답에는 사용량이 오지 않아 직접 센다)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return sum(len(enc.encode(t)) for t in texts)
    except Exception:  # 인코딩 파일을 못 받는 환경 — 글자 수로 어림
        return sum(len(t) for t in texts) // 2
