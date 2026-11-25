"""영어 면접 질문 음성 (services/tts.py · GET /api/interviews/{id}/speech/{index}) — OpenAI 는 가짜로."""

import pytest
from sqlalchemy import select

from education.config import get_settings
from education.db import models as m
from education.services import tts

from test_interview import OPIC_SETUP, run


class FakeSpeech:
    calls: list = []
    fail = False

    def __init__(self):
        self.audio = self
        self.speech = self

    def create(self, **kw):
        FakeSpeech.calls.append(kw)
        if FakeSpeech.fail:
            raise RuntimeError("tts down")
        return type("R", (), {"read": lambda self: b"ID3-fake-mp3"})()


@pytest.fixture
def fake_tts(monkeypatch, tmp_path):
    FakeSpeech.calls, FakeSpeech.fail = [], False
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "_tts")
    monkeypatch.setattr(tts, "_client", FakeSpeech)
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    return FakeSpeech


def test_english_question_is_read_in_fixed_female_voice_and_cached(client, auth, db, fake_tts, new_user):
    d = run(client, auth, "opic", OPIC_SETUP)
    r = client.get(f"/api/interviews/{d['id']}/speech/0", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3-fake-mp3"
    call = fake_tts.calls[0]
    assert call["voice"] == "marin" and call["model"] == "gpt-4o-mini-tts" and "natural" in call["instructions"].lower()
    assert call["input"] == " ".join(d["turns"][0]["q"].split())
    # 같은 질문은 다시 만들지 않는다 (다른 사람의 같은 질문도)
    assert client.get(f"/api/interviews/{d['id']}/speech/0", headers=auth).status_code == 200
    other = new_user()
    d2 = run(client, other, "opic", OPIC_SETUP)
    if d2["turns"][0]["q"] == d["turns"][0]["q"]:
        client.get(f"/api/interviews/{d2['id']}/speech/0", headers=other)
    assert len(fake_tts.calls) == 1
    assert db.scalars(select(m.LLMCall.purpose).where(m.LLMCall.purpose == "tts")).all() == ["tts"]
    # 남의 면접 · 없는 문항은 읽지 않는다
    assert client.get(f"/api/interviews/{d['id']}/speech/0", headers=other).status_code == 404
    assert client.get(f"/api/interviews/{d['id']}/speech/99", headers=auth).status_code == 404


def test_korean_interview_and_failure_fall_back_to_browser(client, auth, db, fake_tts):
    d = run(client, auth, "job", {"job": "백엔드 개발자"})
    assert client.get(f"/api/interviews/{d['id']}/speech/0", headers=auth).status_code == 404  # 한국어는 브라우저 음성
    fake_tts.fail = True
    e = run(client, auth, "toeic", {})
    assert client.get(f"/api/interviews/{e['id']}/speech/0", headers=auth).status_code == 404
    assert fake_tts.calls[-1]["instructions"].startswith("You are a clear, professional female narrator")
    assert db.scalars(select(m.LLMCall.ok).where(m.LLMCall.purpose == "tts")).all() == [False]
