"""AI 면접 모드 — AI 없이(질문 은행 + 측정값 리포트)와 가짜 AI(질문 계획·꼬리질문·리포트) 모두."""

from education.services import interview
from education.services.llm import LLMResult, Usage

OPIC_SETUP = {"role": "학생", "home": "가족과 함께", "hobbies": "jogging, movies", "target": "IH"}
LONG_EN = ("I usually go jogging along the river near my house three times a week because it helps me clear my mind "
           "and stay healthy, and last summer I even ran my first half marathon with my older brother which was amazing")


def run(client, auth, kind="opic", setup=OPIC_SETUP) -> dict:
    r = client.post("/api/interviews", json={"kind": kind, "setup": setup}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_kinds_list(client, auth):
    kinds = client.get("/api/interviews/kinds", headers=auth).json()
    opic = next(k for k in kinds if k["key"] == "opic")
    assert opic["lang"] == "en" and opic["mains"] == 6 and "IH" in opic["levels"]
    assert any(f["key"] == "role" and f["required"] for f in opic["fields"])


def test_start_validates(client, auth):
    assert client.post("/api/interviews", json={"kind": "nope"}, headers=auth).status_code == 422
    r = client.post("/api/interviews", json={"kind": "opic", "setup": {"hobbies": "x"}}, headers=auth)
    assert r.status_code == 422 and "지금 하는 일" in r.json()["detail"]
    # 고를 수 없는 값은 버린다
    d = run(client, auth, setup={**OPIC_SETUP, "target": "SUPER"})
    assert "target" not in d["setup"]


def test_flow_without_ai(client, auth):
    d = run(client, auth)
    assert d["by_ai"] is False and d["current"] == 0 and d["mains"] == 6
    assert d["turns"][0]["q"].startswith("Let's start")
    assert "jogging" in " ".join(interview.OPIC.bank(OPIC_SETUP, __import__("random").Random(1)))
    iid = d["id"]
    for i in range(6):
        text = LONG_EN if i % 2 == 0 else ("um I like like movies" if i == 1 else "")
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": text, "sec": 60}, headers=auth).json()
    assert d["status"] == "answered" and d["current"] is None and len(d["turns"]) == 6  # AI 없으면 꼬리질문 없음
    assert client.post(f"/api/interviews/{iid}/answers", json={"text": "x"}, headers=auth).status_code == 409
    d = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()
    rep = d["report"]
    assert d["status"] == "done" and rep["by_ai"] is False and rep["level"] in interview.OPIC.levels
    assert rep["metrics"]["skipped"] == 2 and rep["metrics"]["fillers"] >= 2 and rep["metrics"]["rate_unit"] == "단어/분"
    assert any("답하지 않은 질문" in t for t in rep["improve"])
    assert len(rep["per"]) == 6
    rows = client.get("/api/interviews", headers=auth).json()
    assert rows[0]["id"] == iid and rows[0]["level"] == rep["level"]


def test_finish_early_and_owner_only(client, auth):
    from conftest import signup
    iid = run(client, auth)["id"]
    client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 40}, headers=auth)
    d = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()
    assert d["status"] == "done" and d["report"]["metrics"]["total"] == 1
    other_auth = signup(client, name="남")
    assert client.get(f"/api/interviews/{iid}", headers=other_auth).status_code == 404
    assert client.delete(f"/api/interviews/{iid}", headers=auth).status_code == 204


def test_measure():
    m = interview.measure("음 저는 그 학생이에요 음 그러니까 열심히 해요", 30, "ko")
    assert m["fillers"] >= 3 and m["syllables"] > 10 and m["rate"]
    e = interview.measure("Um, I like, you know, movies", 10, "en")
    assert e["words"] == 6 and e["fillers"] == 3


class FakeLLM:
    def __init__(self):
        self.calls = []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        self.calls.append(schema.__name__)
        if schema is interview.Plan:
            data = interview.Plan(questions=[f"AI question {i + 1}?" for i in range(6)])
        elif schema is interview.FollowUp:
            data = interview.FollowUp(ask=True, question="Can you give a specific example?")
        else:
            n = prompt.count("질문: ")
            data = interview.Report(level="IH", score=78, summary="좋아요", strengths=["구체적"], improve=["시제"],
                                    items=[interview.ItemFeedback(score=70, feedback="좋음", better="Better answer.") for _ in range(n)])
        return LLMResult(data=data, usage=Usage(model=model))


def test_flow_with_ai(client, auth, monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(interview, "get_llm", lambda: llm)
    d = run(client, auth)
    assert d["by_ai"] is True and d["turns"][0]["q"] == "AI question 1?"
    iid = d["id"]
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    assert d["turns"][-1]["q"] == "AI question 2?"  # 첫 질문(자기소개) 뒤에는 꼬리질문 없음
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    assert d["turns"][-1]["follow"] is True  # 두 번째부터 꼬리질문
    while d["status"] == "active":
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    follows = [t for t in d["turns"] if t["follow"]]
    assert len(follows) == interview.OPIC.follow_ups and len(d["turns"]) == 6 + len(follows)
    d = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()
    rep = d["report"]
    assert rep["by_ai"] and rep["level"] == "IH" and rep["score"] == 78 and len(rep["items"]) == len(d["turns"])
    assert llm.calls.count("Plan") == 1 and llm.calls.count("Report") == 1


KO_ANSWER = ("네 저는 지난 학기에 동아리에서 결제 서버를 맡아 응답 시간을 800밀리초에서 200밀리초로 줄였습니다 "
             "처음에는 원인을 몰라서 로그를 하나씩 확인했고 결국 데이터베이스 인덱스 문제를 찾아 고쳤습니다 "
             "이 경험으로 숫자로 문제를 정의하는 습관이 생겼습니다")


def test_job_interview_without_ai(client, auth):
    assert client.post("/api/interviews", json={"kind": "job", "setup": {}}, headers=auth).status_code == 422  # 직무는 필수
    d = run(client, auth, kind="job", setup={"job": "백엔드 개발자", "company": "유레카", "career": "신입", "jd": "Python, SQL"})
    assert d["lang"] == "ko" and d["kind_info"]["levels"] == [] and d["turns"][0]["q"].startswith("먼저 1분")
    assert any("유레카" in q or "백엔드 개발자" in q for q in [t["q"] for t in d["turns"]] + interview.JOB.bank(d["setup"], __import__("random").Random(3)))
    iid = d["id"]
    while d["status"] == "active":
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": KO_ANSWER, "sec": 70}, headers=auth).json()
    assert len(d["turns"]) == 6 and d["turns"][-1]["q"].startswith("마지막으로")
    rep = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()["report"]
    assert rep["level"] == "" and 0 < rep["score"] <= 100 and rep["metrics"]["rate_unit"] == "음절/분" and rep["metrics"]["rate"]


def test_admission_interview_bank(client, auth):
    import random
    assert client.post("/api/interviews", json={"kind": "admission", "setup": {"track": "학사편입"}}, headers=auth).status_code == 422
    qs = interview.ADMISSION.bank({"track": "학사편입", "major": "전자전기공학부", "school": "고려대학교"}, random.Random(1))
    assert len(qs) == 6 and "고려대학교 전자전기공학부" in qs[1] and "전압" in qs[2]
    med = interview.ADMISSION.bank({"track": "의·치의학전문대학원", "major": "의학과"}, random.Random(2))
    assert "의사" in med[1] and any("환자" in q or "의료" in q for q in med[3:])  # 의전원은 윤리·상황 질문이 꼭 하나
    d = run(client, auth, kind="admission", setup={"track": "대학원", "major": "컴퓨터학과"})
    assert d["kind_info"]["answer_sec"] == 120 and d["mains"] == 6
    kinds = [k["key"] for k in client.get("/api/interviews/kinds", headers=auth).json()]
    assert kinds == ["opic", "toeic", "job", "aicomp", "admission"]


def test_camera_and_mic_allowed_for_interview(client):
    """AI 면접의 내 모습(카메라)·받아쓰기(마이크)를 서버 헤더가 막지 않는다 — 예전에 camera=() 로 막혀 있었다."""
    pp = client.get("/api/health").headers["Permissions-Policy"]
    assert "camera=(self)" in pp and "microphone=(self)" in pp and "geolocation=()" in pp


RESUME = ("저는 교내 동아리에서 결제 서버 개발을 맡아 응답 시간을 800ms에서 200ms로 줄였습니다. 처음에는 원인을 몰라 로그를 하나씩 분석했습니다.\n"
          "6개월간 스타트업 인턴으로 일하며 고객 문의 자동 분류 기능을 기획하고 개발해 상담 시간을 30% 단축했습니다.\n"
          "팀 프로젝트에서 의견 갈등이 있었을 때 회의 방식을 바꿔 합의를 이끌었습니다. 저는 성실한 사람입니다.")


def test_resume_based_questions_without_ai(client, auth):
    snips = interview.resume_snippets(RESUME)
    assert len(snips) == 3 and "800ms" in snips[0] and all("성실한 사람" not in s for s in snips)
    d = run(client, auth, kind="job", setup={"company": "토스", "job": "백엔드 개발자", "resume": RESUME})
    iid = d["id"]
    while d["status"] == "active":
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": KO_ANSWER, "sec": 60}, headers=auth).json()
    based = [t for t in d["turns"] if t.get("basis")]
    assert len(based) == 3 and all(t["basis"] in RESUME or t["basis"].rstrip("…") in RESUME for t in based)
    assert any("토스" in t["q"] for t in d["turns"])


def test_resume_basis_from_ai_is_checked(client, auth, monkeypatch):
    class Planner(FakeLLM):
        def structured(self, *, schema, **kw):
            if schema is interview.Plan:
                qs = [f"질문 {i}" for i in range(6)]
                basis = ["", "결제 서버 개발을 맡아 응답 시간을 800ms에서 200ms로", "지어낸 문장 우주 정거장", "", "", ""]
                return interview.LLMResult(data=interview.Plan(questions=qs, basis=basis), usage=interview.Usage(model="m"))
            return super().structured(schema=schema, **kw)
    monkeypatch.setattr(interview, "LLMResult", LLMResult, raising=False)
    monkeypatch.setattr(interview, "Usage", Usage, raising=False)
    monkeypatch.setattr(interview, "get_llm", lambda: Planner())
    d = run(client, auth, kind="aicomp", setup={"company": "토스", "resume": RESUME})
    assert d["by_ai"] and d["turns"][0]["part"] == "기본 질문 · 자기소개" and d["turns"][0]["answer"] == 60
    plan = client.get(f"/api/interviews/{d['id']}", headers=auth).json()
    # 자기소개서에 있는 근거만 붙고, 지어낸 근거는 버린다 — 서버에 저장된 계획으로 확인
    from education.db import models as m  # noqa: F401
    iid = d["id"]
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": "", "sec": 0}, headers=auth).json()
    assert d["turns"][1].get("basis", "").startswith("결제 서버") and d["turns"][1]["answer"] == 90
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": "", "sec": 0}, headers=auth).json()
    assert not d["turns"][2].get("basis")
    assert plan["kind_info"]["time_note"]


def test_toeic_format_and_read_accuracy(client, auth):
    d = run(client, auth, kind="toeic", setup={})
    t0 = d["turns"][0]
    assert d["mains"] == 11 and t0["material"]["type"] == "read" and (t0["prep"], t0["answer"]) == (45, 45)
    iid, text = d["id"], t0["material"]["text"]
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": text, "sec": 40}, headers=auth).json()  # 지문 그대로 읽기
    parts = [d["turns"][1]["part"]]
    while d["status"] == "active":
        t = d["turns"][d["current"]]
        parts.append(t["part"])
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": "I think it is a good idea because it saves time", "sec": 12}, headers=auth).json()
    assert len(d["turns"]) == 11 and not any(t["follow"] for t in d["turns"])  # TOEIC 은 꼬리질문 없음
    assert [t["answer"] for t in d["turns"]] == [45, 45, 30, 30, 15, 15, 30, 15, 15, 30, 60]
    assert d["turns"][2]["material"]["type"] == "picture" and d["turns"][7]["material"]["type"] == "info"
    rep = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()["report"]
    assert rep["per"][0]["read_acc"] == 100 and rep["metrics"]["read_acc"] is not None and rep["level"] in interview.TOEIC.levels
    assert interview.read_accuracy("Thank you for calling the library", "thank you for calling library") >= 80
