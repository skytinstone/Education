"""하네스 1단계 — 프롬프트 레지스트리(버전) · 실행 추적(agent_runs) · 운영 콘솔."""

import re

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

from education.ai import math_check, models, tutor_agent
from education.config import get_settings
from education.db import models as m
from education.harness import prompts
from education.services import generator, tutor
from education.services.intent import Route
from education.services.llm import LLMResult, Usage
from test_ai_stack import call, scripted
from test_generator import FakeLLM, good_problem, verdict

ADMIN = "admin@example.com"
SUBST = "math.calculus.int_methods.substitution_parts"


@pytest.fixture(autouse=True)
def admins(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)


def test_prompt_registry_versions():
    names = prompts.names()
    assert len(names) == 21 and "generator.generator_instructions" in names and "tutor_agent.instructions" in names
    # 코드가 쓰는 지시문과 파일 내용이 같다
    assert generator.GENERATOR_INSTRUCTIONS == prompts.text("generator.generator_instructions")
    assert "\r" not in prompts.text("intent.instructions")
    v = prompts.versions()
    assert all(re.fullmatch(r"[0-9a-f]{8}", x) for x in v.values())
    assert prompts.version("generator.verifier_instructions") == prompts.version("generator.verifier_instructions")


def test_harness_version_changes_with_model(monkeypatch):
    before = prompts.harness_version()
    monkeypatch.setattr(get_settings(), "openai_model_verify", "gpt-6-astra")
    assert prompts.harness_version() != before


def test_generation_runs_are_traced(db):
    # 하나는 통과, 하나는 두 번 다 정답 불일치로 탈락
    llm = FakeLLM([good_problem(), good_problem(stem="다른 문제"), good_problem(stem="또 다른 문제")],
                  [verdict("1"), verdict("2"), verdict("3")])
    report = generator.generate_problems(db, llm, concept_id=SUBST, difficulty=3, count=2, request="치환적분 3점")
    assert len(report.accepted) == 1 and len(report.rejected) == 1
    runs = list(db.scalars(select(m.AgentRun).where(m.AgentRun.kind == "generate")))
    assert {r.status for r in runs} == {"passed", "rejected"}
    ok = next(r for r in runs if r.status == "passed")
    assert ok.problem_id == report.accepted[0] and "요청: 치환적분 3점" in ok.input and "난이도 3" in ok.input
    assert [s["name"] for s in ok.steps] == ["generate", "format_check", "verify"]
    assert ok.steps[2]["data"]["verifier_answer"] == "1" and ok.steps[0]["tokens"]["in"] == 1000
    assert float(ok.cost_usd) == pytest.approx(0.044) and ok.harness_version == prompts.harness_version()
    assert set(ok.prompt_versions) == {"generator.generator_instructions", "generator.verifier_instructions", "generator.repair_instructions"}
    bad = next(r for r in runs if r.status == "rejected")
    # 두 번 시도 — 두 번째 앞에 떨어진 이유를 생성 AI 에 알려 주는 자기 수정 단계
    assert [s["name"] for s in bad.steps] == ["generate", "format_check", "verify", "self_correct", "generate", "format_check", "verify"]
    assert not bad.steps[2]["ok"] and bad.output.startswith("정답 불일치")


def test_tool_check_steps_are_traced(db, monkeypatch):
    messages = [AIMessage(content="", tool_calls=[{"name": "definite_integral", "args": {"expression": "2x e^(x^2)"}, "id": "t1"}]),
                ToolMessage(content="-1 + E ≈ 1.71828", tool_call_id="t1"),
                AIMessage(content="", tool_calls=[{"name": "MathCheck", "args": {}, "id": "t2"}])]
    monkeypatch.setattr(math_check, "enabled", lambda d: True)
    monkeypatch.setattr(math_check, "check", lambda q, a: (
        math_check.MathCheck(checkable=True, computed="e - 1", agrees=True, reason="정적분"), Usage(model="gpt-6.1-sol", input_tokens=50), messages))
    report = generator.generate_problems(db, FakeLLM([good_problem()], [verdict("1")]), concept_id=SUBST, difficulty=3, count=1)
    run = db.scalars(select(m.AgentRun).where(m.AgentRun.problem_id == report.accepted[0])).one()
    names = [s["name"] for s in run.steps]
    assert names == ["generate", "format_check", "verify", "tool:definite_integral", "math_check"]
    assert run.steps[3]["data"]["result"].startswith("-1 + E") and "math_check.instructions" in run.prompt_versions


def test_agent_runs_are_traced_and_admin_can_read(client, auth, db, monkeypatch, new_user):
    model = scripted([call("get_study_status")],
                     [call("AgentReply", reply="오늘은 아직 푼 문제가 없어요.", suggestions=["3문제 내줘"], start_exam=False)])
    monkeypatch.setattr(models, "get_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(tutor_agent, "enabled", lambda: True)

    class RouteLLM:
        def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
            return LLMResult(data=Route(intent="answer", request="", reply="-", suggestions=[]), usage=Usage(model=model))

    monkeypatch.setattr(tutor, "get_llm", lambda: RouteLLM())
    client.post("/api/sessions", json={"text": "오늘 뭐 하지?"}, headers=auth)
    run = db.scalars(select(m.AgentRun).where(m.AgentRun.kind == "agent")).one()
    assert run.status == "answered" and run.input == "오늘 뭐 하지?" and run.output.startswith("오늘은 아직")
    assert [s["name"] for s in run.steps] == ["tool:get_study_status", "agent"]

    admin = new_user(name="운영자", email=ADMIN)
    assert client.get("/api/admin/runs", headers=auth).status_code == 404
    runs = client.get("/api/admin/runs", params={"kind": "agent"}, headers=admin).json()
    assert len(runs) == 1 and runs[0]["tools"] == 1 and runs[0]["status"] == "answered"
    detail = client.get(f"/api/admin/runs/{runs[0]['id']}", headers=admin).json()
    assert detail["steps"][0]["name"] == "tool:get_study_status" and "tutor_agent.instructions" in detail["prompt_versions"]
    h = client.get("/api/admin/harness", headers=admin).json()
    assert h["harness_version"] == prompts.harness_version() and len(h["prompts"]) == 21
    assert h["versions"][0]["kind"] == "agent" and h["versions"][0]["statuses"] == {"answered": 1}
