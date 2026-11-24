"""개념 레슨(모두가 같이 보는 레슨) · 개념과 대화하기 · 내 노트에 담기 — 가짜 LLM 으로 확인한다."""

from sqlalchemy import select

from education.api.routers import learning as learning_router
from education.db import models as m
from education.services.explain import Curve, Graph, Mark
from education.services.lessons import (
    Example, FlowItem, Formula, LessonContent, LessonStep, LessonVerdict, NumberLine, QuizItem, Symbol, TableBlock, Visual,
)
from education.services.llm import LLMResult, Usage
from education.services.tutor_chat import TutorReply

CONCEPT = "math.calculus.int_methods.substitution_parts"


def vis(kind, **kw) -> Visual:
    empty = dict(graph=None, table=None, flow=None, tree=None, numberline=None, bars=None, timeline=None)
    return Visual(kind=kind, title=f"{kind} 그림", caption="여기를 보세요", **{**empty, **kw})


def step(t="단계") -> LessonStep:
    return LessonStep(title=t, text="설명이에요.", math="")


def lesson(**kw) -> LessonContent:
    base = dict(
        hook="치환적분은 미분을 거꾸로 따라가는 길이에요.",
        visuals=[
            vis("graph", graph=Graph(title="f 와 F", x_min=-3, x_max=3, curves=[Curve(label="f", expr="2*x*exp(x^2)"),
                                                                              Curve(label="F", expr="exp(x^2)")],
                                     marks=[Mark(curve=1, x="0", label="최솟값")])),
            vis("graph", graph=Graph(title="깨진 식", x_min=-1, x_max=1, curves=[Curve(label="?", expr="x +* ")], marks=[])),
            vis("table", table=TableBlock(headers=["방법", "언제"], rows=[["치환", "합성함수"], ["부분", "곱"]])),
        ],
        basics=[step("1"), step("2"), step("3")], deep=[step()], exam=[step()],
        formulas=[Formula(name="치환적분", latex=r"\int f(g(x))g'(x)dx", symbols=[Symbol(symbol="g", meaning="안쪽 함수")], when="합성함수")],
        example=Example(question=r"$\int_0^1 2x e^{x^2}dx$", steps=[step()], answer="$e-1$"),
        pitfalls=["구간을 안 바꿈"],
        quiz=[QuizItem(question=f"Q{i}", choices=["a", "b", "c", "d"], answer=2, why="이유") for i in range(3)],
    )
    return LessonContent(**{**base, **kw})


def ok(**kw) -> LessonVerdict:
    return LessonVerdict(**{**dict(accurate=True, issues=[], example_answer="e-1", example_correct=True, quiz_issues=[]), **kw})


class FakeLLM:
    def __init__(self, items: dict):
        self.queues = {k: list(v) for k, v in items.items()}
        self.prompts: dict = {k: [] for k in items}

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        self.prompts[schema].append((instructions, prompt))
        return LLMResult(data=self.queues[schema].pop(0), usage=Usage(model="gpt-6.1-sol", input_tokens=10, output_tokens=20, latency_ms=1))


def use(monkeypatch, llm):
    monkeypatch.setattr(learning_router, "get_llm", lambda: llm)


def test_lesson_is_made_once_and_shared(client, auth, db, monkeypatch, new_user):
    llm = FakeLLM({LessonContent: [lesson()], LessonVerdict: [ok()]})
    use(monkeypatch, llm)
    assert client.get(f"/api/concepts/{CONCEPT}/lesson", headers=auth).json() is None
    r = client.post(f"/api/concepts/{CONCEPT}/lesson", headers=auth)
    assert r.status_code == 201, r.text
    c = r.json()["content"]
    # 그래프 점은 서버가 계산하고, 식이 깨진 그래프는 빠진다
    kinds = [v["kind"] for v in c["visuals"]]
    assert kinds == ["graph", "table"]
    g = c["visuals"][0]["graph"]
    assert len(g["xs"]) > 50 and g["marks"][0]["y"] == 1.0
    assert c["quiz"][0]["answer"] == 2 and c["formulas"][0]["symbols"][0]["symbol"] == "g"
    # 다른 사람은 AI 를 부르지 않고 같은 레슨을 본다
    other = new_user()
    again = client.post(f"/api/concepts/{CONCEPT}/lesson", headers=other)
    assert again.status_code == 201 and again.json()["content"]["hook"] == c["hook"]
    assert len(llm.prompts[LessonContent]) == 1
    assert sorted(db.scalars(select(m.LLMCall.purpose).where(m.LLMCall.purpose.like("lesson_%")))) == ["lesson_generate", "lesson_verify"]


def test_lesson_rejected_then_fixed(client, auth, monkeypatch):
    llm = FakeLLM({LessonContent: [lesson(), lesson(hook="고친 레슨")],
                   LessonVerdict: [ok(quiz_issues=["Q1 정답이 둘"]), ok()]})
    use(monkeypatch, llm)
    r = client.post(f"/api/concepts/{CONCEPT}/lesson", headers=auth)
    assert r.status_code == 201 and r.json()["content"]["hook"] == "고친 레슨"
    assert "퀴즈 오류" in llm.prompts[LessonContent][1][1]  # 돌려보낸 이유를 다음 시도에 알려 준다


def test_lesson_bad_format_fails(client, auth, monkeypatch):
    bad = lesson(quiz=[QuizItem(question="Q", choices=["a", "b"], answer=5, why="")])
    use(monkeypatch, FakeLLM({LessonContent: [bad, bad], LessonVerdict: []}))
    r = client.post(f"/api/concepts/{CONCEPT}/lesson", headers=auth)
    assert r.status_code == 502 and "퀴즈" in r.json()["detail"]


def test_visual_payload_kinds():
    from education.services.lessons import _visual_payload
    assert _visual_payload(vis("flow", flow=[FlowItem(label="a", detail=""), FlowItem(label="b", detail="")]))["flow"][1]["label"] == "b"
    assert _visual_payload(vis("table")) is None  # 칸이 비면 버린다
    nl = _visual_payload(vis("numberline", numberline=NumberLine(min=-2, max=5, points=[], ranges=[])))
    assert nl["numberline"]["max"] == 5
    assert _visual_payload(vis("numberline", numberline=NumberLine(min=3, max=1, points=[], ranges=[]))) is None


def test_concept_chat_modes_and_clips(client, auth, monkeypatch):
    replies = [
        TutorReply(text="쉽게 말하면 거꾸로 미분이에요.", visual=vis("table", table=TableBlock(headers=["a", "b"], rows=[["1", "2"]])),
                   next_question="무시돼야 함", score=50, missing=["무시"]),
        TutorReply(text="좋아요, 구간 변경이 빠졌어요.", visual=None, next_question="구간은 어떻게 바꿀까요?", score=70, missing=["구간 변경"]),
    ]
    llm = FakeLLM({TutorReply: replies})
    use(monkeypatch, llm)
    r = client.post(f"/api/concepts/{CONCEPT}/chat", json={"mode": "explain", "message": "치환적분이 뭐예요?"}, headers=auth).json()
    assert r["visual"]["kind"] == "table" and r["score"] is None and r["next_question"] == "" and r["missing"] == []
    hist = [{"role": "me", "text": "치환적분이 뭐예요?"}, {"role": "tutor", "text": r["text"]}]
    f = client.post(f"/api/concepts/{CONCEPT}/chat", json={"mode": "feynman", "message": "안쪽 함수를 t 로 바꿔요", "history": hist},
                    headers=auth).json()
    assert f["score"] == 70 and f["missing"] == ["구간 변경"]
    instructions, prompt = llm.prompts[TutorReply][1]
    assert "내가 설명해 볼게" in instructions and "[이전 대화]" in prompt and "치환적분이 뭐예요?" in prompt
    assert client.post(f"/api/concepts/{CONCEPT}/chat", json={"mode": "nope"}, headers=auth).status_code == 422
    # 내 노트에 담기
    c = client.post(f"/api/concepts/{CONCEPT}/clips", json={"text": f["text"]}, headers=auth)
    assert c.status_code == 201
    assert [x["text"] for x in client.get(f"/api/concepts/{CONCEPT}/clips", headers=auth).json()] == [f["text"]]
    assert client.delete(f"/api/clips/{c.json()['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/concepts/{CONCEPT}/clips", headers=auth).json() == []
