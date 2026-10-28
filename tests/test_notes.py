"""개인 맞춤 개념 정리 + 암기 카드 — 가짜 LLM 으로 생성·검증·개인화 흐름을 확인한다 (실제 API 를 부르지 않음)."""

from sqlalchemy import select

from education.api.routers import learning as learning_router
from education.db import models as m
from education.services.llm import LLMError, LLMResult, Usage
from education.services.notes import CardDraft, MemoItem, NoteDraft, NoteVerdict, WorkedExample

CONCEPT = "math.calculus.int_methods.substitution_parts"


def draft(**kw) -> NoteDraft:
    base = dict(
        summary="치환적분은 합성함수의 미분을 거꾸로 쓰는 방법이에요.",
        must_memorize=[MemoItem(title="치환적분", body=r"$\int f(g(x))g'(x)\,dx = \int f(t)\,dt$")],
        pitfalls=["치환한 뒤 적분 구간을 바꾸지 않음"],
        example=WorkedExample(question=r"$\int_0^1 2x e^{x^2}\,dx$", solution="$t=x^2$ 로 치환하면 $e-1$"),
        personal_tip="구간 바꾸기를 습관으로 만들어요.",
        cards=[CardDraft(front="치환적분에서 구간은?", back="새 변수의 범위로 바꾼다"),
               CardDraft(front="부분적분 공식은?", back=r"$\int f g' = fg - \int f' g$"),
               CardDraft(front="$\\int e^x dx$ 는?", back="$e^x + C$")],
    )
    return NoteDraft(**{**base, **kw})


def ok_verdict(**kw) -> NoteVerdict:
    return NoteVerdict(**{**dict(accurate=True, example_answer="e-1", example_correct=True, issues=[], card_issues=[]), **kw})


class FakeLLM:
    def __init__(self, drafts: list, verdicts: list):
        self.queues = {NoteDraft: list(drafts), NoteVerdict: list(verdicts)}
        self.prompts = {NoteDraft: [], NoteVerdict: []}

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
        self.prompts[schema].append(prompt)
        item = self.queues[schema].pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, usage=Usage(model="gpt-6.1-sol", input_tokens=1000, output_tokens=2000, latency_ms=5))


def use(monkeypatch, llm):
    monkeypatch.setattr(learning_router, "get_llm", lambda: llm)


def test_creates_verified_note_and_adds_cards(client, auth, db, monkeypatch):
    use(monkeypatch, FakeLLM([draft()], [ok_verdict()]))
    assert client.get(f"/api/concepts/{CONCEPT}/note", headers=auth).json() is None

    r = client.post(f"/api/concepts/{CONCEPT}/note", headers=auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["note"]["content"]["summary"].startswith("치환적분")
    assert "cards" not in body["note"]["content"]  # 카드는 정리 본문이 아니라 내 덱으로
    assert len(body["added_cards"]) == 3

    got = client.get(f"/api/concepts/{CONCEPT}/note", headers=auth).json()
    assert got["content"]["example"]["solution"].endswith("$e-1$")
    deck = client.get("/api/cards", headers=auth).json()
    assert sorted(c["front"] for c in deck if c["concept_id"] == CONCEPT) == sorted(c["front"] for c in body["added_cards"])
    calls = db.scalars(select(m.LLMCall.purpose).where(m.LLMCall.purpose.like("note_%"))).all()
    assert sorted(calls) == ["note_generate", "note_verify"]


def test_regenerate_overwrites_note_and_skips_duplicate_cards(client, auth, monkeypatch):
    new_card = CardDraft(front="치환 후 $dx$ 는?", back="$dt$ 로 바꾼다")
    use(monkeypatch, FakeLLM([draft(), draft(summary="두 번째 정리", cards=[*draft().cards[:2], new_card])], [ok_verdict()] * 2))
    client.post(f"/api/concepts/{CONCEPT}/note", headers=auth)
    second = client.post(f"/api/concepts/{CONCEPT}/note", headers=auth).json()
    assert second["note"]["content"]["summary"] == "두 번째 정리"
    assert [c["front"] for c in second["added_cards"]] == [new_card.front]  # 이미 있는 앞면은 다시 넣지 않음
    assert len([c for c in client.get("/api/cards", headers=auth).json() if c["concept_id"] == CONCEPT]) == 4


def test_rejected_by_verifier_retries_then_fails(client, auth, db, monkeypatch):
    llm = FakeLLM([draft(), draft()], [ok_verdict(accurate=False, issues=["공식 오류"]), ok_verdict(example_correct=False, example_answer="e")])
    use(monkeypatch, llm)
    r = client.post(f"/api/concepts/{CONCEPT}/note", headers=auth)
    assert r.status_code == 502 and "예제 답 불일치" in r.json()["detail"]
    assert client.get(f"/api/concepts/{CONCEPT}/note", headers=auth).json() is None  # 통과 못 한 정리는 저장하지 않음
    assert not [c for c in client.get("/api/cards", headers=auth).json() if c["concept_id"] == CONCEPT]
    assert len(db.scalars(select(m.LLMCall).where(m.LLMCall.purpose.like("note_%"))).all()) == 4  # 비용 기록은 남김


def test_retry_after_card_error_then_pass(client, auth, monkeypatch):
    llm = FakeLLM([draft(), draft()], [ok_verdict(card_issues=["부분적분 공식 부호"]), ok_verdict()])
    use(monkeypatch, llm)
    assert client.post(f"/api/concepts/{CONCEPT}/note", headers=auth).status_code == 201


def test_format_errors_and_llm_errors_retry(client, auth, monkeypatch):
    llm = FakeLLM([draft(cards=draft().cards[:1]), LLMError("타임아웃")], [])
    use(monkeypatch, llm)
    r = client.post(f"/api/concepts/{CONCEPT}/note", headers=auth)
    assert r.status_code == 502 and not llm.prompts[NoteVerdict]  # 형식 오류는 검증 없이 다시 생성


def test_prompt_is_personalized_with_my_wrong_answers(client, auth, new_user, db, monkeypatch):
    pid = db.scalar(select(m.ProblemConcept.problem_id).where(m.ProblemConcept.concept_id == CONCEPT))
    problem = db.get(m.Problem, pid)
    wrong = next(c for c in ("1", "2", "3", "4", "5") if c != problem.answer)
    client.post("/api/attempts", json={"problem_id": pid, "answer": wrong}, headers=auth)

    llm = FakeLLM([draft(), draft()], [ok_verdict(), ok_verdict()])
    use(monkeypatch, llm)
    client.post(f"/api/concepts/{CONCEPT}/note", headers=auth)
    mine = llm.prompts[NoteDraft][0]
    assert "정답률 0%" in mine and f"고른 답 {wrong}" in mine

    client.post(f"/api/concepts/{CONCEPT}/note", headers=new_user())  # 다른 사람: 기록 없음
    assert "기록 없음" in llm.prompts[NoteDraft][1]


def test_notes_are_private_and_need_ai(client, auth, new_user, monkeypatch):
    use(monkeypatch, FakeLLM([draft()], [ok_verdict()]))
    client.post(f"/api/concepts/{CONCEPT}/note", headers=auth)
    assert client.get(f"/api/concepts/{CONCEPT}/note", headers=new_user()).json() is None

    use(monkeypatch, None)
    assert client.post(f"/api/concepts/{CONCEPT}/note", headers=auth).status_code == 503
    assert client.post("/api/concepts/math.calculus/note", headers=auth).status_code in (502, 503)
    assert client.post("/api/concepts/nope/note", headers=auth).status_code == 404


def test_unit_is_not_a_concept(client, auth, monkeypatch):
    use(monkeypatch, FakeLLM([], []))
    r = client.post("/api/concepts/math.calculus/note", headers=auth)
    assert r.status_code == 502 and "단원이 아니라 개념" in r.json()["detail"]
