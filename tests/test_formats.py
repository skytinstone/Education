"""문제 형식 — 객관식 4·5지선다, 주관식(글자), 수치, 서술형(AI 채점), 코스 형식대로 (가짜 LLM)."""

import threading

import pytest
from sqlalchemy import select

from education.api.routers import learning as learning_router
from education.db import models as m
from education.schemas import Domain, ProblemSource, ProblemType, VerificationStatus
from education.services import generator, learning
from education.services.generator import (EssayVerdict, GeneratedEssay, GeneratedNumeric, GeneratedProblem, GeneratedText,
                                          NumericVerdict, RubricItem, TextVerdict, Verdict)
from education.services.llm import LLMResult, Usage
from education.services.review import CriterionScore, EssayGrade

CONCEPT = "physics.physics1.mechanics_energy.kinematics"


class FakeLLM:
    def __init__(self, items):
        self.items, self.lock, self.prompts = list(items), threading.Lock(), []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        with self.lock:
            self.prompts.append((schema, prompt))
            item = next(i for i in self.items if isinstance(i, schema))
            self.items.remove(item)
        return LLMResult(data=item, usage=Usage(model="gpt-6.1-sol", input_tokens=100, output_tokens=100))


def text_problem():
    return GeneratedText(stem="물체가 원래 운동 상태를 유지하려는 성질은?", answer="관성", accepted=["inertia", "관성의 법칙"],
                         solution="뉴턴 제1법칙", traps=[])


def numeric_problem():
    return GeneratedNumeric(stem="2 kg 물체에 19.6 N 의 힘 — 가속도는? (m/s², 소수 첫째 자리)", answer=9.8, unit="m/s²",
                            tolerance=0.05, solution="a = F/m", traps=[])


def essay_problem():
    return GeneratedEssay(stem="관성의 법칙을 예를 들어 설명하시오.", model_answer="버스가 갑자기 서면 몸이 앞으로 쏠린다 …",
                          rubric=[RubricItem(criterion="관성의 정의", points=4), RubricItem(criterion="알맞은 예시", points=6)],
                          solution="정의와 예시가 모두 필요", traps=["정의만 쓰고 예시 빠뜨림"])


def test_generate_each_format(db):
    llm = FakeLLM([text_problem(), TextVerdict(answer="Inertia", work="", well_posed=True, issues=[]),
                   numeric_problem(), NumericVerdict(answer=9.81, work="", well_posed=True, issues=[]),
                   essay_problem(), EssayVerdict(well_posed=True, model_answer_ok=True, work="", issues=[])])
    ids = {}
    for qtype in ("text", "numeric", "essay"):
        report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=2, count=1, question_type=qtype)
        assert len(report.accepted) == 1, report.reasons
        ids[qtype] = report.accepted[0]
    t, n, e = (db.get(m.Problem, ids[k]) for k in ("text", "numeric", "essay"))
    assert t.problem_type == "text" and t.answer == "관성" and "inertia" in t.answer_spec["accepted"]
    assert n.answer == "9.8" and n.answer_spec == {"unit": "m/s²", "tolerance": 0.05}
    assert e.answer.startswith("버스가") and e.answer_spec["max_score"] == 10 and len(e.answer_spec["rubric"]) == 2
    assert any("수치형" in p for s, p in llm.prompts if s is GeneratedNumeric)


def test_wrong_verifier_answer_rejects_text_and_numeric(db):
    llm = FakeLLM([text_problem(), TextVerdict(answer="관성력", work="", well_posed=True, issues=[]),
                   text_problem(), TextVerdict(answer="가속도", work="", well_posed=True, issues=[]),
                   numeric_problem(), NumericVerdict(answer=4.9, work="", well_posed=True, issues=[]),
                   numeric_problem(), NumericVerdict(answer=19.6, work="", well_posed=True, issues=[])])
    for qtype in ("text", "numeric"):
        report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=2, count=1, question_type=qtype)
        assert not report.accepted and "정답 불일치" in report.reasons[0]


def test_four_choice_course(db, client, auth):
    course = db.get(m.Course, "physics.physics1")
    course.choice_count = 4
    db.flush()
    five = GeneratedProblem(stem="Q", choices=["a", "b", "c", "d", "e"], answer="1", solution="s", traps=[])
    four = GeneratedProblem(stem="Q", choices=["a", "b", "c", "d"], answer="4", solution="s", traps=[])
    llm = FakeLLM([five, four, Verdict(answer="4", work="", well_posed=True, issues=[])])
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=2, count=1)
    assert len(db.get(m.Problem, report.accepted[0]).choices) == 4  # 5개 보기는 형식 오류로 다시 만듦
    assert any("4지선다" in p for s, p in llm.prompts if s is GeneratedProblem)


def test_auto_uses_course_formats(db):
    course = db.get(m.Course, "physics.physics1")
    course.formats = ["text", "numeric"]
    db.flush()
    llm = FakeLLM([text_problem(), TextVerdict(answer="관성", work="", well_posed=True, issues=[]),
                   numeric_problem(), NumericVerdict(answer=9.8, work="", well_posed=True, issues=[])])
    report = generator.generate_problems(db, llm, concept_id=CONCEPT, difficulty=2, count=2, question_type="auto")
    assert sorted(db.get(m.Problem, pid).problem_type for pid in report.accepted) == ["numeric", "text"]


def add_problem(db, pid, ptype, answer, spec=None):
    db.add(m.Problem(id=pid, domain=Domain.PHYSICS, difficulty=2, problem_type=ProblemType(ptype), stem="문제", answer=answer,
                     answer_spec=spec, solution="해설", source=ProblemSource.GENERATED, verification=VerificationStatus.VERIFIED))
    db.flush()
    db.add(m.ProblemConcept(problem_id=pid, concept_id=CONCEPT))
    db.flush()


@pytest.mark.parametrize("answer, ok", [(" Inertia ", True), ("관성 의 법칙", True), ("관성", True), ("가속도", False)])
def test_grade_text(client, auth, db, answer, ok):
    add_problem(db, "t1", "text", "관성", {"accepted": ["관성", "inertia", "관성의 법칙"]})
    assert client.post("/api/attempts", json={"problem_id": "t1", "answer": answer}, headers=auth).json()["correct"] is ok


@pytest.mark.parametrize("answer, ok", [("9.8", True), ("9.82 m/s²", True), ("49/5", True), ("1,000", False), ("구점팔", False)])
def test_grade_numeric(client, auth, db, answer, ok):
    add_problem(db, "n1", "numeric", "9.8", {"unit": "m/s²", "tolerance": 0.05})
    assert client.post("/api/attempts", json={"problem_id": "n1", "answer": answer}, headers=auth).json()["correct"] is ok
    assert learning.parse_number("1,000") == 1000 and learning.parse_number("3/4") == 0.75


def test_grade_essay_with_ai(client, auth, db, monkeypatch):
    add_problem(db, "e1", "essay", "모범 답안", {"rubric": [{"criterion": "정의", "points": 4}, {"criterion": "예시", "points": 6}],
                                              "max_score": 10})
    grade = lambda a, b: EssayGrade(criteria=[CriterionScore(criterion="정의", points=4, earned=a, comment="-"),  # noqa: E731
                                              CriterionScore(criterion="예시", points=6, earned=b, comment="-")], summary="요약")
    monkeypatch.setattr(learning_router, "get_llm", lambda: FakeLLM([grade(4, 9)]))  # 9 는 배점 6 으로 깎인다
    r = client.post("/api/attempts", json={"problem_id": "e1", "answer": "관성은 …" * 20}, headers=auth).json()
    assert r["correct"] is True and r["score"] == 10 and r["feedback"]["criteria"][1]["earned"] == 6

    monkeypatch.setattr(learning_router, "get_llm", lambda: FakeLLM([grade(2, 3)]))
    r = client.post("/api/attempts", json={"problem_id": "e1", "answer": "짧은 답"}, headers=auth).json()
    assert r["correct"] is False and r["score"] == 5 and r["wrong_note_id"]  # 60% 미만 → 오답노트
    attempt = db.scalars(select(m.Attempt).where(m.Attempt.problem_id == "e1").order_by(m.Attempt.created_at)).all()[-1]
    assert attempt.score == 5 and attempt.feedback["summary"] == "요약"

    monkeypatch.setattr(learning_router, "get_llm", lambda: None)
    assert client.post("/api/attempts", json={"problem_id": "e1", "answer": "답"}, headers=auth).status_code == 503
