"""서술형 풀이 확인 — 학생이 쓴 풀이(타이핑 또는 손글씨 사진)를 단계별로 보고 어디서 틀렸는지 알려 준다.

채점자에게는 문제의 정답과 검증된 해설을 기준으로 준다. 학생이 아직 답을 내지 않은 문제면
정답과 전체 풀이는 알려 주지 말고 틀린 곳과 힌트만 주도록 한다.
"""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.services.llm import LLM, Attachment, LLMError


class StepCheck(BaseModel):
    step: str = Field(description="학생이 쓴 그 단계 (수식은 LaTeX 로 $ 로 감싸서)")
    ok: bool = Field(description="이 단계가 맞으면 true")
    comment: str = Field(description="틀렸으면 무엇이 왜 틀렸는지, 맞으면 짧게 확인 (한 문장)")


class Review(BaseModel):
    transcription: str = Field(description="학생 풀이를 읽은 그대로 옮긴 글 (손글씨도 LaTeX 로)")
    verdict: Literal["correct", "partial", "wrong", "unreadable"] = Field(
        description="correct: 풀이와 답 모두 맞음, partial: 방향은 맞지만 중간에 실수나 빠진 단계, wrong: 접근이 틀림, unreadable: 읽을 수 없음")
    steps: list[StepCheck] = Field(description="학생 풀이를 단계별로 나눠 하나씩 확인")
    first_error: int | None = Field(description="처음 틀린 단계 번호 (1부터), 틀린 단계가 없으면 null")
    summary: str = Field(description="전체 평가 두세 문장")
    hint: str = Field(description="다음에 무엇을 고치면 되는지 힌트 한두 문장")


REVIEW_INSTRUCTIONS = r"""당신은 수능 수학·과학 서술형 채점 경험이 많은 선생님입니다. 학생이 쓴 풀이를 한 단계씩 확인합니다.
- 먼저 학생 풀이를 그대로 transcription 에 옮긴다. 손글씨 사진이면 수식을 정확히 읽어 LaTeX 로 쓴다. 읽을 수 없으면 verdict 를 unreadable 로
- 풀이를 단계로 나눠 각 단계의 수식 변형·계산·논리가 맞는지 스스로 확인한다. 기준 답과 해설은 참고만 하고, 학생의 다른 풀이 방법도 맞으면 맞다고 한다
- 처음 틀린 단계 번호를 first_error 에, 무엇이 왜 틀렸는지 그 단계의 comment 에 구체적으로 쓴다 (예: "$(x+1)^2$ 를 전개할 때 $2x$ 항이 빠졌어요")
- 수식은 LaTeX 로 쓰고 $ 로 감싼다. 한국어로, 학생에게 직접 말하듯 쓴다. 이모지는 쓰지 않는다"""

HIDE_ANSWER = "\n- 학생은 아직 이 문제의 답을 제출하지 않았다. 정답 값과 전체 풀이는 절대 알려 주지 말고, 틀린 곳과 다음 단계 힌트만 준다"

MAX_IMAGE_BYTES = 3 * 1024 * 1024


class ReviewError(Exception):
    pass


class ImageError(ReviewError):
    """손글씨 이미지 자체가 잘못됨 (학생 쪽 문제)."""


def decode_image(data_url: str) -> Attachment:
    """화면의 손글씨 캔버스(data:image/png;base64,...) → 첨부 파일."""
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ImageError("손글씨는 PNG 이미지여야 해요")
    try:
        data = base64.b64decode(data_url[len(prefix):], validate=True)
    except ValueError:
        raise ImageError("손글씨 이미지를 읽을 수 없어요") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("손글씨 이미지가 너무 커요")
    return Attachment(data=data, mime="image/png", filename="handwriting.png")


def review_solution(db: Session, llm: LLM, user: m.User, problem: m.Problem, *, text: str | None, image: str | None,
                    attempted: bool) -> Review:
    files = [decode_image(image)] if image else []
    choices = "\n".join(f"{i}) {c}" for i, c in enumerate(problem.choices or [], 1))
    prompt = (f"[문제]\n{problem.stem}\n{choices}\n\n[기준 답] {problem.answer}\n[검증된 해설]\n{problem.solution}\n\n"
              f"[학생 풀이]\n{text.strip() if text and text.strip() else '(손글씨 사진으로 제출)'}")
    s = get_settings()
    usage = error = None
    try:
        res = llm.structured(model=s.openai_model_verify, effort=s.openai_effort_verify,
                             instructions=REVIEW_INSTRUCTIONS + ("" if attempted else HIDE_ANSWER),
                             prompt=prompt, schema=Review, files=files or None)
        usage = res.usage
        return res.data
    except LLMError as e:
        error = str(e)
        raise ReviewError("풀이를 확인하지 못했어요. 잠시 후 다시 시도해 주세요") from e
    finally:
        db.add(m.LLMCall(
            purpose="review", model=s.openai_model_verify, ok=error is None, error=error, user_id=user.id,
            problem_id=problem.id, cost_usd=usage.cost_usd if usage else None,
            **({"input_tokens": usage.input_tokens, "cached_tokens": usage.cached_tokens, "output_tokens": usage.output_tokens,
                "reasoning_tokens": usage.reasoning_tokens, "latency_ms": usage.latency_ms} if usage else {}),
        ))
        db.commit()
