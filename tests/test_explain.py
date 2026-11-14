"""계산·설명 질문 — 풀이·그래프·SymPy 검산. 실제 AI 대신 정해 둔 풀이를 돌려주는 가짜 LLM 을 쓴다."""

import pytest
from sqlalchemy import select

from education.db import models as m
from education.services import explain, mathcheck, tutor
from education.services.explain import Check, Curve, Explanation, Graph, Mark, Step
from education.services.llm import LLMResult, Usage


class FakeLLM:
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        assert schema is Explanation
        self.prompts.append(prompt)
        return LLMResult(data=self.answers.pop(0), usage=Usage(model="gpt-6.1-sol", input_tokens=500, output_tokens=800, latency_ms=5))


def integral(answer="(1/2)*atan(x/2)", curves=None):
    return Explanation(
        summary=r"$\int \frac{1}{4+x^2}dx = \frac{1}{2}\arctan\frac{x}{2} + C$ 이에요.",
        principle=r"역탄젠트 적분 공식 $\int \frac{1}{a^2+x^2}dx = \frac{1}{a}\arctan\frac{x}{a} + C$ 에서 $a=2$ 예요.",
        steps=[Step(title="식 변형하기", text="분모를 $4(1+(x/2)^2)$ 로 묶어요.", math=r"\int \frac{1}{4+x^2}dx"),
               Step(title="치환하기", text="$u = x/2$ 로 놓아요.", math="")],
        result=r"\frac{1}{2}\arctan\left(\frac{x}{2}\right) + C",
        graph=Graph(title="f(x)와 부정적분 F(x)", x_min=-6, x_max=6,
                    curves=curves or [Curve(label="f(x) = 1/(4+x²)", expr="1/(4+x^2)"),
                                      Curve(label="F(x) = (1/2)arctan(x/2)", expr="(1/2)*atan(x/2)")],
                    marks=[Mark(curve=0, x="0", label="최댓값"), Mark(curve=1, x="0", label="원점")]),
        check=Check(kind="antiderivative", expr="1/(4+x^2)", answer=answer, a="", b=""),
    )


@pytest.mark.parametrize("text,expected", [
    ("1/(4+x^2) 적분해 줘", True),
    ("∫ 2x e^(x^2) dx 계산해줘", True),
    ("x^3 미분하면 뭐야?", True),
    ("lim x→0 sin x / x 값은?", True),
    ("왜 로그 밑변환 공식이 성립해?", True),
    ("치환적분 3점짜리 5문제 내줘", False),
    ("미적분 문제 만들어 줘", False),
    ("6월 모평 스타일로 화학 2문제", False),
    ("안녕", False),
])
def test_detects_explain_requests(text, expected):
    assert explain.is_explain_request(text) is expected


def test_explanation_is_verified_and_graph_is_computed_by_server(db, auth, client):
    user = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    line, payload = explain.explain(db, FakeLLM(integral()), user, "1/(4+x^2) 적분해 줘")
    assert payload["check"]["status"] == "verified" and "미분" in payload["check"]["note"]
    assert "검산" in line
    g = payload["graph"]
    assert len(g["xs"]) == 241 and [s["slot"] for s in g["series"]] == [0, 1]
    # 점의 y 는 AI 가 아니라 서버가 계산한다: f(0) = 1/4, F(0) = 0
    assert [(mk["x"], mk["y"]) for mk in g["marks"]] == [(0, 0.25), (0, 0)]
    assert db.scalar(select(m.LLMCall.purpose).where(m.LLMCall.user_id == user.id)) == "explain"


def test_wrong_answer_is_retried_with_feedback(db, auth):
    user = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    llm = FakeLLM(integral(answer="atan(x/2)"), integral())
    _, payload = explain.explain(db, llm, user, "1/(4+x^2) 적분해 줘")
    assert payload["check"]["status"] == "verified"
    assert len(llm.prompts) == 2 and "맞지 않았어요" in llm.prompts[1]


def test_still_wrong_after_retry_is_flagged(db, auth):
    user = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    line, payload = explain.explain(db, FakeLLM(integral(answer="atan(x/2)"), integral(answer="atan(x)")), user, "적분해 줘 1/(4+x^2)")
    assert payload["check"]["status"] == "mismatch" and "확인" in line


def test_unsafe_graph_expression_is_dropped(db, auth):
    user = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    bad = [Curve(label="hack", expr='__import__("os").system("x")')]
    _, payload = explain.explain(db, FakeLLM(integral(curves=bad)), user, "1/(4+x^2) 적분해 줘")
    assert payload["graph"] is None and payload["check"]["status"] == "verified"
    with pytest.raises(mathcheck.MathParseError):
        mathcheck.parse("x.__class__")


def test_chat_returns_and_syncs_explanation(client, auth, monkeypatch):
    monkeypatch.setattr(tutor, "get_llm", lambda: FakeLLM(integral()))
    s = client.post("/api/sessions", json={"text": "1/(4+x^2) 적분해 줘"}, headers=auth).json()
    ai = s["messages"][1]
    assert ai["problems"] == [] and ai["explanation"]["check"]["status"] == "verified"
    synced = client.get("/api/sync", headers=auth).json()["sessions"][0]["messages"][1]
    assert synced["explanation"]["graph"]["title"] == "f(x)와 부정적분 F(x)"


def test_problem_requests_still_make_problems(client, auth, monkeypatch):
    monkeypatch.setattr(tutor, "get_llm", lambda: None)  # AI 없으면 문제 은행
    s = client.post("/api/sessions", json={"text": "치환적분 2문제 내줘"}, headers=auth).json()
    assert s["messages"][1]["explanation"] is None and s["messages"][1]["problems"]
