"""다른 풀이 보기 — 문제마다 한 번 만들고 같이 본다. 가짜 LLM 으로 확인한다."""

from sqlalchemy import select

from education.api.routers import learning as learning_router
from education.db import models as m
from education.services.explain import Curve, Graph, Mark, Step
from education.services.llm import LLMResult, Usage
from education.services.solutions import Method, Methods

PID = "pb_log"


def method(name: str, graph: Graph | None = None) -> Method:
    return Method(name=name, when="이럴 때 좋아요", summary="핵심이에요.",
                  steps=[Step(title="1", text="첫 단계", math="x"), Step(title="2", text="둘째", math="")],
                  result="3", graph=graph)


class FakeLLM:
    def __init__(self, items):
        self.items, self.prompts = list(items), []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        assert schema is Methods
        self.prompts.append(prompt)
        return LLMResult(data=self.items.pop(0), usage=Usage(model="gpt-6.1-sol", input_tokens=10, output_tokens=20, latency_ms=1))


def use(monkeypatch, llm):
    monkeypatch.setattr(learning_router, "get_llm", lambda: llm)


def test_methods_need_an_answer_first(client, auth, monkeypatch):
    use(monkeypatch, FakeLLM([]))
    assert client.get(f"/api/problems/{PID}/methods", headers=auth).status_code == 409
    assert client.post(f"/api/problems/{PID}/methods", headers=auth).status_code == 409
    assert client.post("/api/problems/nope/methods", headers=auth).status_code == 404


def test_methods_made_once_and_shared(client, auth, db, monkeypatch, new_user):
    g = Graph(title="넓이", x_min=0, x_max=2, curves=[Curve(label="f", expr="2*x"), Curve(label="깨짐", expr="x +* ")],
              marks=[Mark(curve=0, x="1", label="점")])
    llm = FakeLLM([Methods(methods=[method("정석"), method("그래프로", g), method("빠르게")])])
    use(monkeypatch, llm)
    client.post("/api/attempts", json={"problem_id": PID, "answer": "1"}, headers=auth)
    assert client.get(f"/api/problems/{PID}/methods", headers=auth).json() is None
    r = client.post(f"/api/problems/{PID}/methods", headers=auth)
    assert r.status_code == 201, r.text
    ms = r.json()["methods"]
    assert [x["name"] for x in ms] == ["정석", "그래프로", "빠르게"]
    # 그래프 점은 서버가 계산하고, 깨진 식은 빠진다
    assert ms[0]["graph"] is None and len(ms[1]["graph"]["series"]) == 1 and ms[1]["graph"]["marks"][0]["y"] == 2.0
    assert "[정답]" in llm.prompts[0] and "[문제]" in llm.prompts[0]
    # 다른 사람은 AI 를 부르지 않고 같은 풀이를 본다
    other = new_user()
    client.post("/api/attempts", json={"problem_id": PID, "answer": "2"}, headers=other)
    again = client.post(f"/api/problems/{PID}/methods", headers=other)
    assert again.status_code == 201 and again.json()["methods"][0]["name"] == "정석"
    assert len(llm.prompts) == 1
    assert list(db.scalars(select(m.LLMCall.purpose).where(m.LLMCall.purpose == "methods"))) == ["methods"]


def test_methods_too_few_fails(client, auth, monkeypatch):
    use(monkeypatch, FakeLLM([Methods(methods=[method("하나뿐")])]))
    client.post("/api/attempts", json={"problem_id": PID, "answer": "1"}, headers=auth)
    r = client.post(f"/api/problems/{PID}/methods", headers=auth)
    assert r.status_code == 502 and "두 가지" in r.json()["detail"]
