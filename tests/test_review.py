"""서술형 풀이 확인 — 가짜 LLM 으로 흐름을 확인한다 (실제 API 를 부르지 않음)."""

import base64
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from education.api.routers import learning as learning_router
from education.db import models as m
from education.schemas import Domain, ProblemSource, ProblemType
from education.services.llm import LLMError, LLMResult, Usage
from education.services.review import HIDE_ANSWER, Review, StepCheck

PID = "pb_subst"


def review(**kw) -> Review:
    base = dict(transcription=r"$t=x^2$, $dt=2x\,dx$ ...", verdict="partial",
                steps=[StepCheck(step="$t=x^2$ 로 치환", ok=True, comment="좋아요"),
                       StepCheck(step=r"$\int_0^1 e^t dt = e$", ok=False, comment="아래끝 0 을 넣은 값을 빼지 않았어요")],
                first_error=2, summary="치환은 맞지만 정적분 계산에서 실수", hint="$F(1)-F(0)$ 을 계산해 보세요")
    return Review(**{**base, **kw})


class FakeLLM:
    def __init__(self, result):
        self.result, self.calls = result, []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        self.calls.append({"instructions": instructions, "prompt": prompt, "files": files})
        if isinstance(self.result, Exception):
            raise self.result
        return LLMResult(data=self.result, usage=Usage(model="gpt-6.1-sol", input_tokens=500, output_tokens=800))


def use(monkeypatch, llm):
    monkeypatch.setattr(learning_router, "get_llm", lambda: llm)


def png_data_url() -> str:
    buf = BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_typed_solution_is_reviewed_and_answer_hidden_before_attempt(client, auth, db, monkeypatch):
    llm = FakeLLM(review())
    use(monkeypatch, llm)
    r = client.post(f"/api/problems/{PID}/review", json={"text": "t = x^2 로 치환하면 ... = e"}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "partial" and body["first_error"] == 2 and body["steps"][1]["ok"] is False
    assert HIDE_ANSWER in llm.calls[0]["instructions"]  # 아직 안 푼 문제: 정답 숨김
    assert "t = x^2" in llm.calls[0]["prompt"] and llm.calls[0]["files"] is None
    assert db.scalar(select(m.LLMCall.purpose).where(m.LLMCall.problem_id == PID)) == "review"

    client.post("/api/attempts", json={"problem_id": PID, "answer": "2"}, headers=auth)
    client.post(f"/api/problems/{PID}/review", json={"text": "다시"}, headers=auth)
    assert HIDE_ANSWER not in llm.calls[1]["instructions"]  # 답을 낸 뒤에는 정답과 비교해 설명해도 됨


def test_handwriting_is_sent_as_image(client, auth, monkeypatch):
    llm = FakeLLM(review(verdict="correct", first_error=None))
    use(monkeypatch, llm)
    r = client.post(f"/api/problems/{PID}/review", json={"image": png_data_url()}, headers=auth)
    assert r.status_code == 200
    f = llm.calls[0]["files"][0]
    assert f.mime == "image/png" and f.data.startswith(b"\x89PNG")


def test_review_validation_and_errors(client, auth, new_user, db, monkeypatch):
    use(monkeypatch, FakeLLM(review()))
    assert client.post(f"/api/problems/{PID}/review", json={"text": "  "}, headers=auth).status_code == 422
    assert client.post(f"/api/problems/{PID}/review", json={"image": "data:image/jpeg;base64,AAAA"}, headers=auth).status_code == 422
    assert client.post(f"/api/problems/{PID}/review", json={"image": "data:image/png;base64,@@@"}, headers=auth).status_code == 422
    assert client.post("/api/problems/nope/review", json={"text": "풀이"}, headers=auth).status_code == 404
    # 남이 올린 기출 문제는 보이지 않는다
    other = db.scalar(select(m.User).order_by(m.User.created_at.desc()))
    db.add(m.Problem(id="private_1", domain=Domain.MATH, difficulty=3, problem_type=ProblemType.MULTIPLE_CHOICE, stem="비공개",
                     choices=["1", "2", "3", "4", "5"], answer="1", solution="-", source=ProblemSource.PAST_EXAM,
                     owner_user_id=other.id))
    db.flush()
    assert client.post("/api/problems/private_1/review", json={"text": "풀이"}, headers=new_user()).status_code == 404

    use(monkeypatch, FakeLLM(LLMError("timeout")))
    assert client.post(f"/api/problems/{PID}/review", json={"text": "풀이"}, headers=auth).status_code == 502
    use(monkeypatch, None)
    assert client.post(f"/api/problems/{PID}/review", json={"text": "풀이"}, headers=auth).status_code == 503
