"""코스 — 출제 범위로 AI 가 개념 트리를 만들고, 모두에게 공개되고, 그 코스로 문제를 만든다 (가짜 LLM)."""

from sqlalchemy import select

from education.api.routers import courses as courses_router
from education.db import models as m
from education.services import generator, tutor
from education.services.courses import ConceptDraft, CourseDraft, UnitDraft
from education.services.generator import GeneratedProblem, Verdict
from education.services.llm import LLMResult, Usage

SCOPE = "7. Techniques of Integration\n10. Parametric Equations and Polar Coordinates"


def draft(**kw) -> CourseDraft:
    base = dict(
        title="편입 수학 (미적분학)", category="수학", domain="math", level="대학", language="en",
        aliases=["편입수학", "미적분학"], choice_count=5, formats=["multiple_choice"],
        units=[UnitDraft(name="적분 기법 (Techniques of Integration)", concepts=[
                   ConceptDraft(name="부분적분 (Integration by Parts)", prerequisites=[]),
                   ConceptDraft(name="삼각치환 (Trigonometric Substitution)", prerequisites=["부분적분 (Integration by Parts)"])]),
               UnitDraft(name="매개변수 방정식과 극좌표", concepts=[ConceptDraft(name="극좌표 넓이", prerequisites=[])])],
    )
    return CourseDraft(**{**base, **kw})


class FakeLLM:
    def __init__(self, items):
        self.items, self.prompts = list(items), []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        self.prompts.append((schema, instructions, prompt))
        item = self.items.pop(0)
        return LLMResult(data=item, usage=Usage(model="gpt-6.1-sol", input_tokens=100, output_tokens=200))


def make_course(client, headers, monkeypatch, llm=None):
    monkeypatch.setattr(courses_router, "get_llm", lambda: llm or FakeLLM([draft()]))
    r = client.post("/api/courses", json={"title": "편입 수학", "exam": "편입", "textbook": "Stewart Calculus 9/E",
                                          "scope_text": SCOPE}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_course_tree(client, auth, monkeypatch):
    body = make_course(client, auth, monkeypatch)
    c = body["course"]
    assert (c["title"], c["exam"], c["level"], c["language"], c["source"], c["mine"]) == ("편입 수학 (미적분학)", "편입", "대학", "en", "user", True)
    assert (c["units"], c["concepts"]) == (2, 3) and "편입수학" in c["aliases"]
    names = [x["name"] for x in body["concepts"]]
    assert names[0] == c["title"] and names[1].startswith("적분 기법")  # 뿌리 → 단원 순서
    concepts = {x["name"]: x for x in body["concepts"]}
    trig = concepts["삼각치환 (Trigonometric Substitution)"]
    assert trig["prerequisites"] == [concepts["부분적분 (Integration by Parts)"]["id"]]
    assert all(x["course_id"] == c["id"] for x in body["concepts"])


def test_courses_are_public(client, auth, new_user, monkeypatch):
    cid = make_course(client, auth, monkeypatch)["course"]["id"]
    other = new_user()
    listed = {x["id"]: x for x in client.get("/api/courses", headers=other).json()}
    assert listed[cid]["mine"] is False and listed["math.calculus"]["source"] == "template"
    assert client.get(f"/api/courses/{cid}", headers=other).status_code == 200
    # 처음 받는 개념: 공식 템플릿 + 내 코스 — 남의 코스는 프로젝트를 만들면 들어온다
    sync = lambda h: {c["course_id"] for c in client.get("/api/sync", headers=h).json()["concepts"]}  # noqa: E731
    assert cid in sync(auth) and cid not in sync(other) and "math.math1" in sync(other)
    client.post("/api/projects", json={"name": "편입 준비", "subject_id": cid}, headers=other)
    assert cid in sync(other)


def test_custom_course_generation_uses_course_context(client, auth, monkeypatch):
    cid = make_course(client, auth, monkeypatch)["course"]["id"]
    pid = client.post("/api/projects", json={"name": "편입", "subject_id": cid}, headers=auth).json()["id"]
    problem = GeneratedProblem(stem=r"$\int x e^x dx$ 는?", choices=["$xe^x - e^x + C$", "$xe^x$", "$e^x$", "$x^2e^x$", "$0$"],
                               answer="1", solution="부분적분", traps=[])
    llm = FakeLLM([problem, Verdict(answer="1", work="", well_posed=True, issues=[])])
    monkeypatch.setattr(tutor, "get_llm", lambda: llm)
    ai = client.post("/api/sessions", json={"text": "부분적분 1문제", "project_id": pid}, headers=auth).json()["messages"][1]
    assert "새로 만들고" in ai["text"] and ai["problems"][0]["concept_ids"][0].startswith(f"{cid}.u1.")
    gen_instructions, gen_prompt = llm.prompts[0][1], llm.prompts[0][2]
    assert "코스: 편입 수학 (미적분학)" in gen_prompt and "Stewart Calculus 9/E" in gen_prompt and "언어 영어" in gen_prompt
    assert "고등학교 2015" not in gen_instructions


def test_course_names_are_recognized(client, auth, db, monkeypatch):
    cid = make_course(client, auth, monkeypatch)["course"]["id"]
    assert generator.detect_subject("편입수학 3문제", db) == cid
    assert generator.detect_subject("수학II 문제", db) == "math.math2"  # 공식 코스도 DB 별칭으로
    user = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    plan = generator.plan_request(db, "편입수학 극좌표 2문제", user=user)
    assert plan.concept_id.startswith(f"{cid}.u2.")


def test_bad_tree_is_retried_and_ai_required(client, auth, monkeypatch):
    bad = draft(units=[])
    body = make_course(client, auth, monkeypatch, llm=FakeLLM([bad, draft()]))
    assert body["course"]["units"] == 2
    monkeypatch.setattr(courses_router, "get_llm", lambda: None)
    assert client.post("/api/courses", json={"title": "회계원리", "scope_text": "1장"}, headers=auth).status_code == 503


def test_course_survives_owner_leaving(client, new_user, db, monkeypatch):
    owner = new_user(email="maker@example.com")
    cid = make_course(client, owner, monkeypatch)["course"]["id"]
    client.request("DELETE", "/api/me", json={"confirm_email": "maker@example.com"}, headers=owner)
    course = db.get(m.Course, cid)
    assert course is not None and course.owner_user_id is None  # 공개 코스라 남는다
