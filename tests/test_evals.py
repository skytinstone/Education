"""하네스 2단계 — 평가 (골든셋 · 지표 · 녹화/재생 · 점수판)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from education.ai import math_check
from education.config import get_settings
from education.db import models as m
from education.harness.evals import runner
from education.services.generator import FORMATS, GeneratedProblem, Verdict
from education.services.llm import LLMResult, Usage

ADMIN = "admin@example.com"
GOLD = {c["id"]: c for c in runner.load("verify")}
BASELINE = Path(runner.__file__).parent / "cassettes" / "baseline.json"


@pytest.fixture(autouse=True)
def admins(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)


def test_golden_set_is_well_formed():
    ids = [c["id"] for c in runner.load("verify")]
    assert len(ids) == len(set(ids)) >= 25
    defects = {"wrong_key", "multiple_answers", "missing_condition", "no_correct_choice", "subtle_wrong_key"}
    for c in GOLD.values():
        assert c["label"] in ("good", "bad") and 1 <= int(c["answer"]) <= len(c["choices"]) == 5
        assert (c["label"] == "good") == (c.get("defect") is None) and (c.get("defect") in defects | {None})
    # 정답 번호만 바꾼 망가진 문제는 같은 본문의 좋은 문제와 답이 달라야 한다
    for b in (c for c in GOLD.values() if c.get("defect") in ("wrong_key", "subtle_wrong_key")):
        twin = next(g for g in GOLD.values() if g["label"] == "good" and g["stem"] == b["stem"])
        assert twin["answer"] != b["answer"] and twin["choices"] == b["choices"]
    r = runner.load("retrieval")
    assert len({c["id"] for c in r}) == len(r) >= 5


def _question(c) -> str:
    _, _, _, question_of, _ = FORMATS["multiple_choice"]
    return question_of(GeneratedProblem(stem=c["stem"], choices=c["choices"], answer=c["answer"], solution="-", traps=[]))


# 검증 AI 는 정답을 모른 채 문제만 본다 — 같은 문제(본문 + 보기)의 좋은 판이 있으면 그 정답을 말한다
GOOD_BY_QUESTION = {_question(c): c["answer"] for c in GOLD.values() if c["label"] == "good"}


class FakeVerifier:
    """좋은 문제와 같은 문제면 그 정답을, 그 밖(복수 정답 · 조건 누락 · 맞는 보기 없음)이면 결함을 말한다.
    등비급수 문제만 일부러 틀리게 답한다 (검증 AI 의 실수 → 검산 에이전트가 잡는지 보려고)."""

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        assert schema is Verdict
        ans = GOOD_BY_QUESTION.get(prompt)
        if ans is None:
            v = Verdict(answer="none", work="-", well_posed=False, issues=["결함"])
        else:
            v = Verdict(answer="5" if r"\left(\frac{1}{3}" in prompt else ans, work="-", well_posed=True, issues=[])
        return LLMResult(data=v, usage=Usage(model="gpt-6.1-sol", input_tokens=500, output_tokens=100))


def fake_math(question, answer):
    """출제 정답이 좋은 문제의 정답과 같으면 일치 (도구로 계산한 셈)."""
    ok = answer.split("번")[0] == GOOD_BY_QUESTION.get(question)
    return (math_check.MathCheck(checkable=True, computed="계산값", agrees=ok, reason="도구"),
            Usage(model="gpt-6.1-sol", input_tokens=200, output_tokens=20), [])


def test_live_eval_metrics_and_replay_is_identical(db, monkeypatch):
    monkeypatch.setattr(math_check, "check", fake_math)
    run, tape = runner.run(db, llm=FakeVerifier(), mode="live", suites=("verify",), workers=2)
    v = run.metrics["verify"]
    assert run.status == "done" and v["cases"] == len(GOLD) and v["good"] == 29
    # 등비급수: 검증 AI 가 틀려서 좋은 문제 하나를 잘못 버리고, 망가진 쪽은 검산 에이전트가 잡는다
    by_id = {c["id"]: c for c in run.cases["verify"]}
    assert by_id["g_geo_series"]["decision"] == "reject" and by_id["b_series_key"]["caught_by"] == "math_check"
    assert v["false_reject_rate"] == round(1 / 29, 4) and v["detection_rate"] == 1.0
    assert v["math_check_added"] > 0 and v["verifier_detection"] < 1.0
    assert v["by_defect"]["wrong_key"]["detected"] == 1.0 and v["cost_usd"] > 0
    assert set(tape["verify"]) == set(GOLD)
    # 재생하면 AI 없이 같은 지표가 나온다
    again, _ = runner.run(db, mode="replay", cassette=json.loads(json.dumps(tape)), suites=("verify",))
    assert again.metrics["verify"] | {"avg_ms": 0} == v | {"avg_ms": 0} and again.mode == "replay"


def test_retrieval_metrics_from_recording(db):
    tape = {"retrieval": {
        "r_series": [{"problem_id": "a", "concepts": ["x"], "similarity": 0.9}, {"problem_id": "b", "concepts": ["math.calculus.seq_limit.series"], "similarity": 0.8}],
        "r_thermo": [{"problem_id": "c", "concepts": ["physics.physics1.mechanics_energy.thermodynamics"], "similarity": 0.9}],
        "r_python": [{"problem_id": "d", "concepts": ["y"], "similarity": 0.5}],
    }}
    run, _ = runner.run(db, mode="replay", cassette=tape, suites=("retrieval",))
    r = run.metrics["retrieval"]
    assert r["cases"] == 3 and r["recall_at_3"] == round(2 / 3, 4) and r["mrr"] == round((1 / 2 + 1) / 3, 4)


@pytest.mark.skipif(not BASELINE.exists(), reason="기준점 카세트가 아직 없어요")
def test_baseline_cassette_replays_to_recorded_metrics(db):
    """운영에서 실제 AI 로 녹화한 기준점 — 판정 로직이나 지표 계산을 바꿔서 숫자가 달라지면 CI 가 알려 준다."""
    tape = json.loads(BASELINE.read_text(encoding="utf-8"))
    run, _ = runner.run(db, mode="replay", cassette=tape)
    for suite, metrics in tape["metrics"].items():
        assert {k: v for k, v in run.metrics[suite].items() if k != "avg_ms"} == {k: v for k, v in metrics.items() if k != "avg_ms"}


def test_admin_eval_endpoints(client, db, new_user, monkeypatch):
    monkeypatch.setattr(math_check, "check", fake_math)
    run, _ = runner.run(db, llm=FakeVerifier(), mode="live", suites=("verify",), workers=1)
    admin = new_user(name="운영자", email=ADMIN)
    user = new_user()
    assert client.get("/api/admin/evals", headers=user).status_code == 404
    lst = client.get("/api/admin/evals", headers=admin).json()
    assert lst[0]["id"] == str(run.id) and lst[0]["metrics"]["verify"]["detection_rate"] == 1.0
    detail = client.get(f"/api/admin/evals/{run.id}", headers=admin).json()
    assert len(detail["cases"]["verify"]) == len(GOLD) and detail["prompt_versions"]
    assert client.post("/api/admin/evals/run", headers=admin).status_code == 503  # 테스트에는 AI 가 없다
    assert db.scalar(select(m.EvalRun.status).where(m.EvalRun.id == run.id)) == "done"


# ---------- 3단계: 자기 수정 루프 · 생성 평가 ----------
from education.services import generator  # noqa: E402
from test_generator import FakeLLM, good_problem, verdict  # noqa: E402


class PromptLLM(FakeLLM):
    def __init__(self, *a):
        super().__init__(*a)
        self.prompts = []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        self.prompts.append((schema.__name__, prompt))
        return super().structured(model=model, effort=effort, instructions=instructions, prompt=prompt, schema=schema)


@pytest.mark.parametrize("on", [True, False])
def test_self_correction_feeds_back_the_reason(db, monkeypatch, on):
    monkeypatch.setattr(get_settings(), "ai_self_correct", on)
    llm = PromptLLM([good_problem(answer="2"), good_problem()], [verdict("1", issues=["보기 1이 맞음"]), verdict("1")])
    report = generator.generate_problems(db, llm, concept_id="math.calculus.int_methods.substitution_parts", difficulty=3, count=1)
    assert len(report.accepted) == 1
    second = [p for name, p in llm.prompts if name == "GeneratedProblem"][1]
    assert ("[직전 시도" in second and "정답 불일치" in second and "검증자가 직접 푼 답: 1" in second) is on
    run = db.scalars(select(m.AgentRun).where(m.AgentRun.problem_id == report.accepted[0])).one()
    assert ("self_correct" in [x["name"] for x in run.steps]) is on
    assert "generator.repair_instructions" in run.prompt_versions


def test_generate_eval_measures_and_rolls_back(db, monkeypatch):
    monkeypatch.setattr(runner, "load", lambda suite: [{"id": "gen_x", "concept_id": "math.calculus.int_methods.substitution_parts",
                                                       "difficulty": 3, "count": 2}] if suite == "generate" else [])
    before = db.scalar(select(func.count()).select_from(m.Problem))
    # 하나는 첫 시도에 통과, 하나는 고쳐서 두 번째에 통과
    llm = FakeLLM([good_problem(), good_problem(answer="2"), good_problem(stem="고친 문제")], [verdict("1"), verdict("1"), verdict("1")])
    run, _ = runner.run(db, llm=llm, mode="live", suites=("generate",), workers=1)
    g = run.metrics["generate"]
    assert g["requested"] == 2 and g["accepted"] == 2 and g["yield"] == 1.0 and g["first_try_pass"] == 0.5
    assert g["avg_attempts"] == 1.5 and g["self_corrected"] == 1 and g["self_correct_success"] == 1.0 and g["cost_per_accepted"] > 0
    # 만든 문제는 되돌렸다 — 문제 은행과 실행 기록에 남지 않는다
    assert db.scalar(select(func.count()).select_from(m.Problem)) == before
    assert db.scalar(select(func.count()).select_from(m.AgentRun)) == 0
