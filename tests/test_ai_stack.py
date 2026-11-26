"""AI 에이전트 계층 — Tool Calling(SymPy 도구 · 검산 에이전트 · 대화 에이전트) · RAG(pgvector).

실제 API 는 부르지 않는다: LangChain 의 가짜 채팅 모델이 '이 도구를 이 순서로 부른다'를 재생하고,
임베딩은 같은 글이면 같은 벡터를 주는 가짜 임베딩(DeterministicFakeEmbedding)을 쓴다.
"""

import hashlib
import itertools
import random

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import select

from education.ai import math_check, models, rag, tutor_agent
from education.ai.sympy_tools import are_equal, calculate, definite_integral, derivative, limit_of, solve_equation
from education.config import get_settings
from education.db import models as m
from education.schemas import VerificationStatus
from education.services import generator, tutor
from education.services.intent import Route
from education.services.llm import LLMResult, Usage
from test_generator import FakeLLM, good_problem, verdict

LOG = "math.math1.exp_log.log_properties"
_ids = itertools.count()


class FakeEmbedder:
    """같은 글이면 같은 벡터, 다른 글이면 거의 직교하는 벡터 (실제 임베딩 API 대신)."""

    def _vec(self, text: str) -> list[float]:
        rnd = random.Random(hashlib.sha256(text.encode()).hexdigest())
        return [rnd.gauss(0, 1) for _ in range(models.EMBED_DIM)]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


class ScriptedModel(GenericFakeChatModel):
    """정해 둔 AIMessage(도구 호출 포함)를 차례로 내는 가짜 채팅 모델."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, **args):
    return {"name": name, "args": args, "id": f"c{next(_ids)}"}


def scripted(*steps):
    msgs = [AIMessage(content="", tool_calls=list(s), usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
            for s in steps]
    return ScriptedModel(messages=iter(msgs))


# ---------- 계산 도구 ----------
def test_sympy_tools_compute_exactly():
    assert calculate.invoke({"expression": "2^10 - 1"}) == "1023"
    assert solve_equation.invoke({"equation": "x^2 - 5x + 6 = 0", "variable": "x"}) == "2, 3"
    assert "1.71828" in definite_integral.invoke({"expression": "2x e^(x^2)", "variable": "x", "lower": "0", "upper": "1"})
    assert derivative.invoke({"expression": "x^3 - 3x", "variable": "x", "at": "2"}) == "9"
    assert limit_of.invoke({"expression": "sin(x)/x", "variable": "x", "point": "0"}) == "1"
    assert are_equal.invoke({"a": "e - 1", "b": "1.718281828"}).startswith("같아요")
    assert are_equal.invoke({"a": "e", "b": "1.7"}).startswith("달라요")


@pytest.mark.parametrize("bad", ["__import__('os')", "x.real", "open(1)", "abc + 1", "1" * 400])
def test_sympy_tools_reject_unsafe_input(bad):
    assert calculate.invoke({"expression": bad}).startswith("오류")


# ---------- 검산 에이전트 (Tool Calling) ----------
def test_math_check_agent_uses_tools_and_finds_wrong_key(monkeypatch):
    model = scripted(
        [call("definite_integral", expression="2x e^(x^2)", variable="x", lower="0", upper="1")],
        [call("are_equal", a="E - 1", b="E")],
        [call("MathCheck", checkable=True, computed="e - 1", agrees=False, reason="적분값은 e-1 인데 출제 정답은 e")],
    )
    monkeypatch.setattr(models, "get_chat_model", lambda *a, **k: model)
    out, usage = math_check.check("∫₀¹ 2x·e^(x²) dx 의 값은?", "2번 (e)")
    assert out.checkable and not out.agrees and out.computed == "e - 1"
    assert usage.input_tokens == 300 and usage.output_tokens == 60  # 모델 호출 3번의 합


def test_generator_rejects_when_tool_check_disagrees(db, monkeypatch):
    seen = []

    def fake_check(question, answer):
        seen.append(answer)
        return math_check.MathCheck(checkable=True, computed="e - 1", agrees=answer.startswith("1번"), reason="도구 계산"), \
            Usage(model="gpt-6.1-sol", input_tokens=100, output_tokens=10)

    monkeypatch.setattr(math_check, "check", fake_check)
    monkeypatch.setattr(math_check, "enabled", lambda domain: domain == "math")
    # 첫 문제: 생성·검증 AI 가 둘 다 2번이라고 했지만 도구로 계산하면 1번 → 버리고 다시 / 두 번째: 1번 → 통과
    llm = FakeLLM([good_problem(answer="2"), good_problem()], [verdict("2"), verdict("1")])
    report = generator.generate_problems(db, llm, concept_id="math.calculus.int_methods.substitution_parts", difficulty=3, count=1)
    assert len(report.accepted) == 1 and seen == ["2번 (e)", "1번 (e − 1)"]
    purposes = sorted(c.purpose for c in db.scalars(select(m.LLMCall).where(m.LLMCall.problem_id == report.accepted[0])))
    assert purposes.count("math_check") == 2


def test_generator_keeps_problem_when_tool_check_fails(db, monkeypatch):
    def broken(question, answer):
        raise generator.LLMError("시간 초과")
    monkeypatch.setattr(math_check, "check", broken)
    monkeypatch.setattr(math_check, "enabled", lambda domain: True)
    report = generator.generate_problems(db, FakeLLM([good_problem()], [verdict("1")]),
                                         concept_id="math.calculus.int_methods.substitution_parts", difficulty=3, count=1)
    assert len(report.accepted) == 1  # 검산이 실패해도 이미 독립 검증을 통과한 문제는 막지 않는다


# ---------- RAG ----------
@pytest.fixture
def fake_embedder(monkeypatch):
    emb = FakeEmbedder()
    monkeypatch.setattr(models, "get_embedder", lambda: emb)
    return emb


def test_rag_index_search_and_owner_scope(db, fake_embedder, new_user, client):
    assert rag.backfill(db) >= 10  # 시드 문제
    assert rag.backfill(db) == 0  # 이미 있으면 건너뜀
    log = db.get(m.Problem, "pb_log")
    hits = rag.search(db, None, rag.problem_text(log), k=3)
    assert hits[0].problem.id == "pb_log" and hits[0].similarity > 0.999
    assert rag.search(db, None, rag.problem_text(log), concept_id=LOG, k=5)[0].problem.id == "pb_log"
    # 남이 올린 문제는 보이지 않는다
    new_user(email="owner@example.com")
    uid = db.scalar(select(m.User.id).where(m.User.email == "owner@example.com"))
    db.add(m.Problem(id="pb_private", domain="math", difficulty=2, problem_type="multiple_choice", stem="비공개 기출 문제",
                     choices=["1", "2", "3", "4", "5"], answer="1", solution="-", source="past_exam",
                     verification=VerificationStatus.VERIFIED, owner_user_id=uid))
    db.flush()
    rag.backfill(db)
    vec = rag.embed(db, ["비공개 기출 문제\n1 / 2 / 3 / 4 / 5"])[0]
    assert "pb_private" not in [h.problem.id for h in rag.similar(db, vec, user=None, k=20)]
    mine = db.get(m.User, uid)
    assert rag.similar(db, vec, user=mine, k=1)[0].problem.id == "pb_private"
    assert db.scalars(select(m.LLMCall.purpose).where(m.LLMCall.purpose == "embed")).first() == "embed"


def test_generator_drops_near_duplicate(db, fake_embedder):
    rag.backfill(db)
    log = db.get(m.Problem, "pb_log")
    same = good_problem(stem=log.stem, choices=log.choices, answer=log.answer)
    report = generator.generate_problems(db, FakeLLM([same], [verdict(log.answer)]), concept_id=LOG, difficulty=1, count=1)
    assert not report.accepted and report.reasons[0].startswith("중복")
    fresh = generator.generate_problems(db, FakeLLM([good_problem(stem="log_3 81 의 값은?")], [verdict("1")]),
                                        concept_id=LOG, difficulty=1, count=1)
    assert len(fresh.accepted) == 1
    # 새로 통과한 문제는 바로 검색에 잡힌다
    assert db.get(m.ProblemEmbedding, fresh.accepted[0]) is not None


# ---------- 대화 에이전트 (LangChain create_agent + 도구) ----------
def test_tutor_agent_answers_with_tools(client, auth, db, monkeypatch, fake_embedder):
    client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "1"}, headers=auth)  # 오답 하나
    model = scripted(
        [call("get_study_status"), call("get_wrong_notes", limit=3)],
        [call("calculate", expression="2^3")],
        [call("AgentReply", reply="오늘 1문제 풀었고 남은 오답이 1개예요.\n• 로그의 정의와 성질부터 다시 봐요",
              suggestions=["로그 3문제 내줘"], start_exam=False)],
    )
    monkeypatch.setattr(models, "get_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(tutor_agent, "enabled", lambda: True)

    class RouteLLM:
        def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
            assert schema is Route
            return LLMResult(data=Route(intent="project_report", request="", reply="(한 번 답)", suggestions=[]),
                             usage=Usage(model=model, input_tokens=10, output_tokens=5))

    monkeypatch.setattr(tutor, "get_llm", lambda: RouteLLM())
    s = client.post("/api/sessions", json={"text": "지금 내 공부 상황 어때?"}, headers=auth).json()
    ai = s["messages"][1]
    assert ai["intent"] == "agent" and ai["text"].startswith("오늘 1문제") and ai["suggestions"] == ["로그 3문제 내줘"]
    assert sorted(c.purpose for c in db.scalars(select(m.LLMCall))) == ["agent", "route"]


def test_tutor_agent_tools_stay_in_user_scope(db, new_user, client, monkeypatch):
    a = new_user()
    new_user(email="b@example.com")
    client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "1"}, headers=a)
    user_b = db.scalar(select(m.User).where(m.User.email == "b@example.com"))
    ctx = tutor_agent.Ctx(db=db, user=user_b, project=None)

    class Rt:
        context = ctx
    # 도구는 AI 가 넘기는 값이 아니라 서버가 정한 사용자로만 조회한다 — B 에게는 A 의 오답이 보이지 않는다
    assert tutor_agent.get_wrong_notes.func(runtime=Rt(), limit=5) == "남은 오답이 없어요."
    assert "오늘 푼 문제: 0개" in tutor_agent.get_study_status.func(runtime=Rt())


def test_agent_falls_back_to_single_answer_on_failure(client, auth, db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("API 다운")
    monkeypatch.setattr(models, "get_chat_model", lambda *a, **k: ScriptedModel(messages=iter([])))
    monkeypatch.setattr(tutor_agent, "enabled", lambda: True)
    monkeypatch.setattr(tutor_agent, "create_agent", boom)

    class RouteLLM:
        def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
            return LLMResult(data=Route(intent="answer", request="", reply="한 번 답이에요", suggestions=[]),
                             usage=Usage(model=model, input_tokens=10, output_tokens=5))

    monkeypatch.setattr(tutor, "get_llm", lambda: RouteLLM())
    ai = client.post("/api/sessions", json={"text": "공부 어떻게 해?"}, headers=auth).json()["messages"][1]
    assert ai["text"] == "한 번 답이에요" and ai["intent"] == "answer"
    failed = db.scalars(select(m.LLMCall).where(m.LLMCall.purpose == "agent")).one()
    assert not failed.ok


def test_settings_have_agent_defaults():
    s = get_settings()
    assert s.embedding_model == "text-embedding-3-small" and 0.9 <= s.rag_duplicate_similarity < 1
