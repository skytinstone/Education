"""대화 의도 판단 — 문제 요청이 아닌 말에 문제를 내지 않고, 이전 대화를 이어받는지. 실제 AI 대신 정해 둔 판단을 돌려준다."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from education.db import models as m
from education.services import intent, tutor
from education.services.explain import Explanation
from education.services.intent import Route
from education.services.llm import LLMError, LLMResult, Usage
from test_explain import integral


class FakeLLM:
    """schema 별로 정해 둔 응답을 차례로 돌려준다 (예외면 raise). 받은 prompt 를 모아 둔다."""

    def __init__(self, routes=(), explanations=()):
        self.queues = {Route: list(routes), Explanation: list(explanations)}
        self.prompts = {Route: [], Explanation: []}

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        if not self.queues.get(schema):  # 정해 두지 않은 호출(문제 만들기 등)은 실패로
            raise LLMError(f"준비하지 않은 호출: {schema.__name__}")
        self.prompts[schema].append(prompt)
        item = self.queues[schema].pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, usage=Usage(model=model, input_tokens=300, output_tokens=100, latency_ms=5))


def route(kind, *, request="", reply="", suggestions=()):
    return Route(intent=kind, request=request, reply=reply, suggestions=list(suggestions))


@pytest.mark.parametrize("text,history,expected", [
    ("치환적분 3문제 내줘", False, "make_problems"),
    ("로그 문제 만들어 줘", False, "make_problems"),
    ("1/(4+x^2) 적분해 줘", False, "explain"),
    ("내가 진행하고 있는 시험 프로젝트에 대해 간략하게 보고 해줘!", False, None),
    ("극한이 뭐야? 설명해줘", False, None),       # 식이 없는 개념 질문은 맥락을 보고 판단
    ("3개월 공부 계획 짜줘", False, None),         # '3개' 가 있어도 문제 요청이 아님
    ("비슷한 거 3문제 더", True, None),            # 앞 대화를 가리키면 AI 가 판단
    ("2번 다시 설명해줘", True, None),
    ("치환적분 3문제 내줘", True, "make_problems"),
])
def test_fast_route(text, history, expected):
    assert intent.fast_route(text, history) == expected


def test_project_report_answers_from_facts_without_problems(client, auth, db, monkeypatch):
    exam = (date.today() + timedelta(days=10)).isoformat()
    pid = client.post("/api/projects", json={"name": "고려대 편입 수학", "subject_id": "math.calculus", "exam_date": exam},
                      headers=auth).json()["id"]
    llm = FakeLLM([route("project_report", reply="시험까지 10일 남았어요.\n• 아직 푼 문제가 없어요",
                         suggestions=["약점 3문제 풀기", "남은 기간 학습 계획 짜줘"])])
    monkeypatch.setattr(tutor, "get_llm", lambda: llm)
    s = client.post("/api/sessions", json={"text": "내가 진행하고 있는 시험 프로젝트에 대해 간략하게 보고 해줘!", "project_id": pid},
                    headers=auth).json()
    ai = s["messages"][1]
    assert ai["problems"] == [] and ai["explanation"] is None and ai["text"].startswith("시험까지 10일")
    assert ai["intent"] == "project_report" and ai["suggestions"] == ["약점 3문제 풀기", "남은 기간 학습 계획 짜줘"]
    facts = llm.prompts[Route][0]
    assert "프로젝트: 고려대 편입 수학" in facts and "(D-" in facts and "이 프로젝트에서 푼 문제: 0개" in facts
    assert "(없음 — 새 대화)" in facts
    # 문제를 만들지 않았다 — 판단 한 번만
    assert [c.purpose for c in db.scalars(select(m.LLMCall))] == ["route"]
    synced = client.get("/api/sync", headers=auth).json()["sessions"][0]["messages"][1]
    assert synced["suggestions"] == ["약점 3문제 풀기", "남은 기간 학습 계획 짜줘"]


def test_follow_up_sees_previous_problems(client, auth, monkeypatch):
    monkeypatch.setattr(tutor, "get_llm", lambda: None)  # 첫 문제는 문제 은행에서
    s = client.post("/api/sessions", json={"text": "치환적분 2문제 내줘"}, headers=auth).json()
    assert s["messages"][1]["problems"]

    llm = FakeLLM([route("explain", request="다음 적분을 풀어 줘: $\\int \\frac{1}{4+x^2}dx$")], [integral()])
    monkeypatch.setattr(tutor, "get_llm", lambda: llm)
    out = client.post(f"/api/sessions/{s['id']}/messages", json={"text": "2번 다시 설명해줘"}, headers=auth).json()
    ai = out[1]
    assert ai["intent"] == "explain" and ai["explanation"]["check"]["status"] == "verified" and ai["problems"] == []
    seen = llm.prompts[Route][0]
    assert "학생: 치환적분 2문제 내줘" in seen and "1번 문제:" in seen and "아직 안 풂" in seen
    assert llm.prompts[Explanation][0] == "학생 질문: 다음 적분을 풀어 줘: $\\int \\frac{1}{4+x^2}dx$"


def test_small_talk_and_clarify_do_not_make_problems(client, auth, monkeypatch):
    llm = FakeLLM([route("clarify", reply="문제를 풀어 볼까요, 지금 현황을 정리해 드릴까요?", suggestions=["문제 2개 풀기", "현황 알려줘"])])
    monkeypatch.setattr(tutor, "get_llm", lambda: llm)
    ai = client.post("/api/sessions", json={"text": "음 뭐하지"}, headers=auth).json()["messages"][1]
    assert ai["intent"] == "clarify" and ai["problems"] == [] and ai["suggestions"] == ["문제 2개 풀기", "현황 알려줘"]


def test_route_failure_falls_back_to_old_rules(client, auth, db, monkeypatch):
    monkeypatch.setattr(tutor, "get_llm", lambda: FakeLLM([LLMError("timeout")]))
    ai = client.post("/api/sessions", json={"text": "미적분학 공부하고 싶어"}, headers=auth).json()["messages"][1]
    assert ai["intent"] == "make_problems" and ai["problems"]  # 예전처럼 문제 은행
    call = db.scalar(select(m.LLMCall).where(m.LLMCall.purpose == "route"))
    assert call is not None and call.ok is False


# ---------- 답변 멈추기 · 질문 고치기 ----------
def test_stop_keeps_question_and_skips_ai(client, auth, db, monkeypatch):
    llm = FakeLLM()  # 정해 둔 응답이 없다 — 부르면 실패로 남는다
    monkeypatch.setattr(tutor, "get_llm", lambda: llm)
    ref = str(uuid.uuid4())
    assert client.post("/api/sessions/stop", json={"ref": ref}, headers=auth).status_code == 204
    assert client.post("/api/sessions/stop", json={"ref": ref}, headers=auth).status_code == 204  # 두 번 눌러도 괜찮다
    s = client.post("/api/sessions", json={"text": "치환적분 3문제 내줘", "ref": ref}, headers=auth).json()
    user, ai = s["messages"]
    assert user["text"] == "치환적분 3문제 내줘" and ai["intent"] == "stopped" and ai["text"] == "답변을 중단했어요."
    assert ai["problems"] == [] and not llm.prompts[Route] and db.scalar(select(m.LLMCall)) is None
    # 다른 ref 로 보낸 질문은 멈추지 않는다
    monkeypatch.setattr(tutor, "get_llm", lambda: None)
    out = client.post(f"/api/sessions/{s['id']}/messages", json={"text": "화학 2문제", "ref": str(uuid.uuid4())}, headers=auth).json()
    assert out[1]["intent"] == "make_problems" and out[1]["problems"]


def test_stop_during_routing_skips_generation(client, auth, monkeypatch):
    """판단 중에 멈추기가 오면 문제 만들기로 넘어가지 않는다."""
    ref = str(uuid.uuid4())

    class StopWhileRouting(FakeLLM):
        def structured(self, **kw):
            if kw["schema"] is Route:
                client.post("/api/sessions/stop", json={"ref": ref}, headers=auth)
            return super().structured(**kw)

    llm = StopWhileRouting([route("make_problems", request="치환적분 2문제")])
    monkeypatch.setattr(tutor, "get_llm", lambda: llm)
    ai = client.post("/api/sessions", json={"text": "아무거나 좀 풀어보고 싶어", "ref": ref}, headers=auth).json()["messages"][1]
    assert ai["intent"] == "stopped" and ai["problems"] == []


def test_edit_question_replaces_it_and_drops_later_turns(client, auth, monkeypatch):
    monkeypatch.setattr(tutor, "get_llm", lambda: None)
    s = client.post("/api/sessions", json={"text": "치환적분 1문제"}, headers=auth).json()
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "화학 2문제"}, headers=auth)
    full = client.get(f"/api/sessions/{s['id']}", headers=auth).json()["messages"]
    assert len(full) == 4
    first = full[0]["id"]
    r = client.post(f"/api/sessions/{s['id']}/messages/{first}/edit", json={"text": "화학 1문제"}, headers=auth)
    assert r.status_code == 200, r.text
    msgs = r.json()["messages"]
    assert [x["role"] for x in msgs] == ["user", "ai"] and msgs[0]["text"] == "화학 1문제" and len(msgs[1]["problems"]) == 1
    assert client.get("/api/sync", headers=auth).json()["sessions"][0]["messages"][0]["text"] == "화학 1문제"
    # AI 답변이나 남의 대화는 고칠 수 없다
    ai_id = msgs[1]["id"]
    assert client.post(f"/api/sessions/{s['id']}/messages/{ai_id}/edit", json={"text": "x"}, headers=auth).status_code == 404
