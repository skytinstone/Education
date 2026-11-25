"""AI 면접 질문 읽어 주기 — 영어 면접(OPIc · TOEIC Speaking)은 서버가 자연스러운 여자 목소리로 만든다.

- OpenAI TTS(gpt-4o-mini-tts)에 목소리(marin)를 고정하고, 말투 지시(instructions)로 실제 면접관처럼 자연스럽게 읽게 한다
- 같은 문장은 한 번만 만들고 파일로 저장해 다시 쓴다 (질문 은행 문장은 모든 사용자가 같이 씀 → 비용이 거의 안 든다)
- 서버에는 그 면접의 질문만 읽게 한다 (아무 글이나 읽히는 데 쓰이지 않게)
- 만들지 못하면 None — 화면은 브라우저 음성(여자 영어 목소리 우선)으로 대신 읽는다
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import openai
from sqlalchemy.orm import Session

from education.config import ROOT, get_settings
from education.db import models as m

log = logging.getLogger(__name__)

MODEL = "gpt-4o-mini-tts"
VOICE = "marin"  # 여자 목소리 (영어 면접 전체에 고정)
VOICES = (VOICE, "coral", "nova")  # marin 을 쓸 수 없는 계정이면 다른 여자 목소리
CACHE_DIR = ROOT / "data" / "uploads" / "_tts"   # 배포해도 남는 폴더 (docker-compose.prod.yml 의 uploads 볼륨)
MAX_CHARS = 1500
# 대략 1분(약 900자) 에 $0.015 — 운영 콘솔 AI 비용에 남기는 추정치
USD_PER_CHAR = 0.015 / 900

STYLE = {
    "opic": ("You are a warm, friendly female OPIc interviewer (Ava) having a relaxed one-on-one conversation. "
             "Speak natural, conversational American English at a comfortable, slightly unhurried pace, with natural intonation, "
             "small pauses at commas and between sentences, and a light, encouraging smile in your voice. Never sound robotic or rushed."),
    "toeic": ("You are a clear, professional female narrator for the TOEIC Speaking test. Speak standard American English at a calm, "
              "even, natural pace with crisp articulation and short natural pauses between sentences. Neutral and polite, not dramatic."),
}
DEFAULT_STYLE = STYLE["opic"]


def available() -> bool:
    return bool(get_settings().openai_api_key)


def _key(text: str, style: str) -> str:
    return hashlib.sha256(f"{MODEL}|{VOICE}|{style}|{text}".encode()).hexdigest()[:40]


def cache_path(text: str, kind: str) -> Path:
    return CACHE_DIR / f"{_key(text, STYLE.get(kind, DEFAULT_STYLE))}.mp3"


def _client() -> openai.OpenAI:
    return openai.OpenAI(api_key=get_settings().openai_api_key, timeout=60, max_retries=1)


def speech(db: Session, user: m.User, text: str, kind: str) -> Path | None:
    """질문 문장의 mp3 경로 — 저장해 둔 게 있으면 그대로, 없으면 만들어 저장한다"""
    text = " ".join(text.split())[:MAX_CHARS]
    if not text:
        return None
    path = cache_path(text, kind)
    if path.exists() and path.stat().st_size > 0:
        return path
    if not available():
        return None
    style = STYLE.get(kind, DEFAULT_STYLE)
    try:
        client = _client()
        for i, voice in enumerate(VOICES):  # 계정에서 쓸 수 없는 목소리면 다음 여자 목소리로
            try:
                data = client.audio.speech.create(model=MODEL, voice=voice, input=text, instructions=style, response_format="mp3").read()
                break
            except openai.BadRequestError:
                if i == len(VOICES) - 1:
                    raise
    except Exception as e:  # noqa: BLE001 — 음성은 없어도 면접은 계속된다 (브라우저 음성으로)
        log.warning("tts failed: %s", e)
        db.add(m.LLMCall(purpose="tts", model=MODEL, ok=False, error=str(e)[:500], user_id=user.id))
        db.commit()
        return None
    if not data:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)  # 다 쓴 뒤에 이름을 바꿔, 반쯤 쓴 파일을 내보내지 않는다
    db.add(m.LLMCall(purpose="tts", model=MODEL, ok=True, user_id=user.id, cost_usd=round(len(text) * USD_PER_CHAR, 6)))
    db.commit()
    return path
