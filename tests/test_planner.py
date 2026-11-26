"""AI 학습 플래너 · 문제 Deep Dive — 가짜 LLM 으로 확인한다."""

from datetime import date, timedelta

from sqlalchemy import select

from education.api.routers import planner as planner_router
from education.db import models as m
from education.services.deepdive import Dive, DiveStep
from education.services.llm import LLMResult, Usage
from education.services.planner import Phase, PlanReview

LOG = "math.math1.exp_log.log_properties"
EXP = "math.math1.exp_log.exponent_rules"  # LOG 의 선수 개념
PID = "pb_log"  # 정답 3번


class FakeLLM:
    def __init__(self, items):
        self.items, self.prompts = list(items), []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        item = self.items.pop(0)
        assert isinstance(item, schema)
        self.prompts.append(prompt)
        return LLMResult(data=item, usage=Usage(model="gpt-6.1-sol", input_tokens=10, output_tokens=20, latency_ms=1))


def use(monkeypatch, llm):
    monkeypatch.setattr(planner_router, "get_llm", lambda: llm)


def project(client, headers, days=30, **kw) -> str:
    body = {"name": "수학I 중간고사", "subject_id": "math.math1", "goal": "1등급",
            "exam_date": (date.today() + timedelta(days=days)).isoformat(), **kw}
    r = client.post("/api/projects", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def solve(client, headers, answer, pid=PID, project_id=None):
    r = client.post("/api/attempts", json={"problem_id": pid, "answer": answer, "project_id": project_id}, headers=headers)
    assert r.status_code == 201, r.text


def concept_of(plan, cid):
    return next(c for c in plan["concepts"] if c["id"] == cid)


def test_plan_before_any_study(client, auth):
    pj = project(client, auth)
    plan = client.get(f"/api/projects/{pj}/plan", headers=auth).json()
    assert 29 <= plan["days_left"] <= 31
    s = plan["summary"]
    assert s["concepts"] > 5 and s["touched"] == 0 and s["accuracy"] is None and s["per_day"] > 0
    assert all(c["status"] == "untouched" for c in plan["concepts"])
    kinds = [t["kind"] for t in plan["tasks"]]
    assert kinds[:2] == ["lesson", "practice"] and "deepdive" not in kinds  # 아직 오답이 없다
    assert plan["review"] is None


def test_plan_finds_weakness_with_peer_data(client, auth, new_user):
    pj = project(client, auth, unit_ids=["math.math1.exp_log"])
    # 다른 학습자 다섯 명분의 기록 — 대부분 맞힌다
    other = new_user()
    for a in ("3", "3", "3", "3", "1"):
        solve(client, other, a)
    solve(client, auth, "1", project_id=pj)
    solve(client, auth, "2", project_id=pj)
    plan = client.get(f"/api/projects/{pj}/plan", headers=auth).json()
    log = concept_of(plan, LOG)
    assert log["status"] == "weak" and log["accuracy"] == 0 and log["peer_accuracy"] == 0.8 and log["open_notes"] == 1
    assert any("다른 학습자 평균(80%)" in r for r in log["reasons"])
    assert plan["concepts"][0]["id"] in (LOG, EXP)
    # 약한 개념의 선수 개념이 함께 올라온다
    exp = concept_of(plan, EXP)
    assert exp["priority"] > log["priority"] and any("선수 개념" in r for r in exp["reasons"])
    # 오늘 푼 기록이 할 일에 저절로 반영되고, 틀린 문제는 Deep Dive 할 일이 된다
    practice = next(t for t in plan["tasks"] if t["key"] == f"practice:{LOG}")
    assert practice["progress"] == 2 and not practice["done"]
    dive = next(t for t in plan["tasks"] if t["kind"] == "deepdive")
    assert dive["problem_id"] == PID and not dive["done"]


def test_plan_task_check_and_privacy(client, auth, new_user):
    pj = project(client, auth)
    plan = client.get(f"/api/projects/{pj}/plan", headers=auth).json()
    lesson = next(t for t in plan["tasks"] if t["kind"] == "lesson")
    r = client.put(f"/api/projects/{pj}/plan/tasks", json={"key": lesson["key"], "done": True}, headers=auth)
    assert next(t for t in r.json()["tasks"] if t["key"] == lesson["key"])["done"]
    r = client.put(f"/api/projects/{pj}/plan/tasks", json={"key": lesson["key"], "done": False}, headers=auth)
    assert not next(t for t in r.json()["tasks"] if t["key"] == lesson["key"])["done"]
    other = new_user()
    assert client.get(f"/api/projects/{pj}/plan", headers=other).status_code == 404


def test_plan_ai_review_uses_feedback(client, auth, db, monkeypatch):
    pj = project(client, auth)
    review = PlanReview(
        headline="지수·로그부터 채워요", diagnosis=["범위 개념 중 0개를 풀었어요"],
        phases=[Phase(title="빈 범위", period="D-30 ~ D-15", focus="안 본 개념부터", concept_ids=[EXP, "없는.개념"]),
                Phase(title="총정리", period="D-14 ~ D-1", focus="실전", concept_ids=[])],
        today_focus=["없는.개념", EXP], advice=["매일 조금씩"], feedback_reply="주말 위주로 바꿨어요")
    llm = FakeLLM([review])
    use(monkeypatch, llm)
    r = client.post(f"/api/projects/{pj}/plan/review", json={"feedback": "평일엔 바빠요"}, headers=auth)
    assert r.status_code == 200, r.text
    plan = r.json()
    rv = plan["review"]
    assert rv["phases"][0]["concept_ids"] == [EXP] and rv["today_focus"] == [EXP]  # 범위 밖 id 는 버린다
    assert rv["feedback_reply"] == "주말 위주로 바꿨어요" and plan["feedback"] == "평일엔 바빠요" and plan["reviewed_at"]
    assert plan["tasks"][0]["concept_id"] == EXP  # AI 가 고른 오늘의 초점이 할 일 맨 앞
    assert "평일엔 바빠요" in llm.prompts[0] and LOG in llm.prompts[0] and "D-" in llm.prompts[0]
    assert list(db.scalars(select(m.LLMCall.purpose).where(m.LLMCall.purpose == "plan"))) == ["plan"]


def test_plan_review_needs_ai(client, auth):
    pj = project(client, auth)
    assert client.post(f"/api/projects/{pj}/plan/review", json={}, headers=auth).status_code == 503


def step(q, answer=1, n=3):
    return DiveStep(question=q, choices=[f"보기{i}" for i in range(1, n + 1)], answer=answer, hint="힌트", explain="설명")


def test_deep_dive_flow(client, auth, db, monkeypatch):
    first = Dive(diagnosis="5 를 3 으로 읽었어요", steps=[step("8 은 2 의 몇 제곱?"), step("잘못", answer=9), step("답은?", answer=3)],
                 takeaway="진수를 거듭제곱으로")
    again = Dive(diagnosis="더 잘게", steps=[step("a"), step("b"), step("c"), step("d")], takeaway="t")
    llm = FakeLLM([first, again])
    use(monkeypatch, llm)
    assert client.post(f"/api/problems/{PID}/deep-dive", json={}, headers=auth).status_code == 409  # 풀기 전
    pj = project(client, auth)
    solve(client, auth, "1", project_id=pj)
    assert client.get(f"/api/problems/{PID}/deep-dive", headers=auth).json() is None
    r = client.post(f"/api/problems/{PID}/deep-dive", json={}, headers=auth)
    assert r.status_code == 201, r.text
    d = r.json()
    assert len(d["steps"]) == 2 and d["rounds"] == 1 and not d["completed"]  # 정답 번호가 보기 밖인 단계는 버린다
    assert "[학생이 낸 답]" in llm.prompts[0] and "1번 (3) — 틀림" in llm.prompts[0]
    # 다시 열면 AI 를 부르지 않는다
    assert client.post(f"/api/problems/{PID}/deep-dive", json={}, headers=auth).json()["id"] == d["id"]
    # 아직 헷갈려요 → 끝난 것으로 치고, 플래너가 그 개념을 올린다
    r = client.patch(f"/api/deep-dives/{d['id']}", json={"answers": [2, 1], "feedback": "confused"}, headers=auth)
    assert r.json()["completed"] and r.json()["answers"] == [2, 1]
    plan = client.get(f"/api/projects/{pj}/plan", headers=auth).json()
    assert concept_of(plan, LOG)["confused"] == 1 and concept_of(plan, LOG)["status"] == "few"  # 한 문제로는 약점이라 하지 않는다
    assert next(t for t in plan["tasks"] if t["kind"] == "deepdive")["done"]
    # 더 잘게 다시 — 이전 기록은 비우고 회차가 오른다
    r = client.post(f"/api/problems/{PID}/deep-dive", json={"retry": True}, headers=auth)
    d2 = r.json()
    assert d2["id"] == d["id"] and d2["rounds"] == 2 and len(d2["steps"]) == 4 and not d2["completed"] and d2["answers"] == []
    assert "더 잘게" in llm.prompts[1]
    assert len(list(db.scalars(select(m.LLMCall).where(m.LLMCall.purpose == "deep_dive")))) == 2


def test_deep_dive_too_few_steps_and_owner(client, auth, new_user, monkeypatch):
    use(monkeypatch, FakeLLM([Dive(diagnosis="x", steps=[step("하나")], takeaway="t")]))
    solve(client, auth, "1")
    r = client.post(f"/api/problems/{PID}/deep-dive", json={}, headers=auth)
    assert r.status_code == 502 and "단계" in r.json()["detail"]
    other = new_user()
    assert client.patch("/api/deep-dives/00000000-0000-0000-0000-000000000000", json={}, headers=other).status_code == 404
