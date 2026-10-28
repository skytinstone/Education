"""AI 문제 생성 + 검증 엔진 — 가짜 LLM 으로 흐름을 검증한다 (실제 API 를 부르지 않음)."""

import threading

import pytest
from sqlalchemy import func, select

from education.db import models as m
from education.schemas import VerificationStatus
from education.services import generator, tutor
from education.services.generator import GeneratedProblem, Verdict
from education.services.llm import LLMError, LLMResult, Usage

CONCEPT = "math.calculus.int_methods.substitution_parts"


def good_problem(**kw) -> GeneratedProblem:
    base = dict(stem="∫₀¹ 2x·e^(x²) dx 의 값은?", choices=["e − 1", "e", "e + 1", "2e", "1"], answer="1",
                solution="t = x² 로 치환하면 e − 1", traps=["치환 후 적분 구간을 안 바꿈"])
    return GeneratedProblem(**{**base, **kw})


class FakeLLM:
    """generate/verify 호출마다 정해 둔 응답을 차례로 돌려준다 (예외면 raise)."""

    def __init__(self, generate: list, verify: list):
        self.queues = {GeneratedProblem: list(generate), Verdict: list(verify)}
        self.lock = threading.Lock()
        self.calls = {GeneratedProblem: 0, Verdict: 0}

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        with self.lock:
            self.calls[schema] += 1
            item = self.queues[schema].pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, usage=Usage(model="gpt-6.1-sol", input_tokens=1000, output_tokens=2000, latency_ms=5))


def verdict(answer="1", well_posed=True, issues=()):
    return Verdict(answer=answer, work="풀이", well_posed=well_posed, issues=list(issues))


def test_accepts_when_verifier_agrees(db):
    llm = FakeLLM([good_problem()], [verdict("1")])
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=3, count=1)
    assert len(report.accepted) == 1 and not report.rejected
    p = db.get(m.Problem, report.accepted[0])
    assert p.verification == VerificationStatus.VERIFIED and p.concept_ids == [CONCEPT]
    assert p.generation_meta["verifier_answer"] == "1"
    calls = db.scalars(select(m.LLMCall).where(m.LLMCall.problem_id == p.id)).all()
    assert sorted(c.purpose for c in calls) == ["generate", "verify"]
    # gpt-6.1-sol: 입력 1000 × $2/M + 출력 2000 × $10/M = $0.022 → 호출 2번
    assert report.cost_usd == pytest.approx(0.044)


def test_answer_mismatch_retries_then_rejects(db):
    llm = FakeLLM([good_problem(), good_problem(stem="다른 문제")], [verdict("2"), verdict("3")])
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=3, count=1)
    assert not report.accepted and len(report.rejected) == 1
    assert "정답 불일치" in report.reasons[0]
    assert llm.calls[GeneratedProblem] == 2  # ai_max_attempts=2
    assert db.get(m.Problem, report.rejected[0]).verification == VerificationStatus.REJECTED


def test_ill_posed_problem_is_rejected_even_if_answer_matches(db):
    llm = FakeLLM([good_problem(), good_problem()], [verdict("1", well_posed=False, issues=["복수 정답"])] * 2)
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=3, count=1)
    assert not report.accepted and "복수 정답" in report.reasons[0]


def test_format_errors_skip_verification(db):
    dup = good_problem(choices=["1", "1", "2", "3", "4"])
    llm = FakeLLM([dup, good_problem()], [verdict("1")])
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=3, count=1)
    assert len(report.accepted) == 1
    assert llm.calls[Verdict] == 1  # 형식 오류 문제는 검증 호출 없이 다시 생성


def test_llm_error_is_logged_and_retried(db):
    llm = FakeLLM([LLMError("rate limit"), good_problem()], [verdict("1")])
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=3, count=1)
    assert len(report.accepted) == 1
    errors = db.scalars(select(m.LLMCall).where(m.LLMCall.ok.is_(False))).all()
    assert len(errors) == 1 and "rate limit" in errors[0].error


def test_generates_several_in_parallel(db):
    llm = FakeLLM([good_problem(stem=f"문제 {i}") for i in range(3)], [verdict("1")] * 3)
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=4, count=3)
    assert len(report.accepted) == 3
    assert {db.get(m.Problem, pid).difficulty for pid in report.accepted} == {4}


def test_rejects_non_concept(db):
    with pytest.raises(ValueError):
        generator.generate_problems(db, FakeLLM([], []), concept_id="math.calculus", difficulty=3, count=1)


# ---------- 요청 분석 ----------
@pytest.mark.parametrize("text, concept, difficulty, count", [
    ("치환적분 4점 3문제 내줘", CONCEPT, 4, 3),
    ("로그의 성질 쉬운 문제", "math.math1.exp_log.log_properties", 1, 2),
    ("중화 반응 킬러 10문제", "chemistry.chemistry1.dynamic_reactions.neutralization", 5, 3),
    ("운동량 보존 문제 1개", "physics.physics1.mechanics_energy.momentum_impulse", 3, 1),
])
def test_plan_request(db, text, concept, difficulty, count):
    plan = generator.plan_request(db, text)
    assert (plan.concept_id, plan.difficulty, plan.count) == (concept, difficulty, count)


def test_plan_reads_subject_name(db, auth, client):
    # 개념 이름 없이 과목만 말해도 그 과목 안에서 고른다 (같은 수학이라도 다른 과목은 아님)
    plan = generator.plan_request(db, "미적분학 5문제 만들어줘", max_count=5)
    assert plan.concept_id.startswith("math.calculus.") and plan.count == 5
    assert generator.plan_request(db, "수1 문제", max_count=5).concept_id.startswith("math.math1.")
    assert generator.plan_request(db, "확통 3등급 대비 문제").concept_id.startswith("math.prob_stat.")
    # 단원 이름이 있으면 그 단원으로 좁힌다
    assert generator.plan_request(db, "미적분 적분법 문제").concept_id.startswith("math.calculus.int_methods.")
    # 내 기록이 있으면 그 과목에서 가장 약한 개념
    client.post("/api/attempts", json={"problem_id": "pb_subst", "answer": "2"}, headers=auth)
    user = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    assert generator.plan_request(db, "미적분 문제", user=user).concept_id == CONCEPT


def test_subject_names_vs_numbers():
    assert generator.detect_subject("수학 10문제") is None  # 수학1 이 아님
    assert generator.detect_subject("수학 2등급 목표") is None  # 수학2 가 아님
    assert generator.detect_subject("물1 3문제") == "physics.physics1"
    assert generator.detect_subject("수학II") == "math.math2"


def test_plan_respects_project_scope(db):
    assert generator.plan_request(db, "치환적분 문제", scope_ids=["physics.physics1"]) is None
    assert generator.plan_request(db, "아무거나 내줘") is None


# ---------- 대화와 연결 ----------
def test_tutor_uses_ai_when_configured(db, monkeypatch, auth, client):
    monkeypatch.setattr(tutor, "get_llm", lambda: FakeLLM([good_problem(), good_problem(stem="두 번째")], [verdict("1")] * 2))
    s = client.post("/api/sessions", json={"text": "치환적분 2문제"}, headers=auth).json()
    ai = s["messages"][1]
    assert "새로 만들고" in ai["text"]
    assert [p["id"].startswith("ai_") for p in ai["problems"]] == [True, True]
    assert all(p["answer"] is None for p in ai["problems"])  # 풀기 전엔 정답 숨김


def test_tutor_falls_back_to_bank(db, monkeypatch, auth, client):
    failing = FakeLLM([good_problem()] * 2, [verdict("5")] * 2)  # 계속 정답 불일치
    monkeypatch.setattr(tutor, "get_llm", lambda: failing)
    s = client.post("/api/sessions", json={"text": "치환적분 1문제"}, headers=auth).json()
    ai = s["messages"][1]
    assert "검증을 통과하지 못해서" in ai["text"]
    assert ai["problems"] and all(not p["id"].startswith("ai_") for p in ai["problems"])
    # 탈락한 AI 문제는 학생에게 나가지 않는다
    rejected = db.scalar(select(func.count()).select_from(m.Problem).where(m.Problem.verification == VerificationStatus.REJECTED))
    assert rejected == 1


def test_tutor_bank_stays_in_requested_subject(db, monkeypatch, auth, client):
    monkeypatch.setattr(tutor, "get_llm", lambda: None)
    ai = client.post("/api/sessions", json={"text": "미적분학 5문제 만들어줘"}, headers=auth).json()["messages"][1]
    assert ai["problems"] and all(c.startswith("math.calculus.") for p in ai["problems"] for c in p["concept_ids"])


def test_tutor_without_ai_uses_bank(db, monkeypatch, auth, client):
    monkeypatch.setattr(tutor, "get_llm", lambda: None)
    ai = client.post("/api/sessions", json={"text": "화학 2문제"}, headers=auth).json()["messages"][1]
    assert ai["text"].startswith("AI 연결 전이라") and len(ai["problems"]) == 2
