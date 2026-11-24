"""AI 면접 모드 — AI 없이(질문 은행 + 측정값 리포트)와 가짜 AI(질문 계획·꼬리질문·리포트) 모두."""

from education.services import interview
from education.services.llm import LLMResult, Usage

SURVEY = {"leisure": "영화 보기, 카페 가기, 공원 가기, 쇼핑하기", "hobby": "음악 감상, 요리하기, 독서", "sport": "조깅, 걷기, 수영",
          "travel": "국내 여행, 해외 여행"}  # 12개
OPIC_SETUP = {"job": "일 경험 없음", "student": "네", "home": "가족과 함께 거주", **SURVEY,
              "level": interview.OPIC_SELF[4], "length": "짧은 연습 (1차 세션 7문항)"}
OPIC_FULL = {**OPIC_SETUP, "length": "실전 (12·15문항)"}
LONG_EN = ("I usually go jogging along the river near my house three times a week because it helps me clear my mind "
           "and stay healthy, and last summer I even ran my first half marathon with my older brother which was amazing")


def run(client, auth, kind="opic", setup=OPIC_SETUP) -> dict:
    r = client.post("/api/interviews", json={"kind": kind, "setup": setup}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_kinds_list(client, auth):
    kinds = client.get("/api/interviews/kinds", headers=auth).json()
    opic = next(k for k in kinds if k["key"] == "opic")
    assert opic["lang"] == "en" and "IH" in opic["levels"] and opic["survey_min"] == 12 and opic["adjust_after"] == 7
    assert opic["replays"] == 1 and opic["prep_sec"] == 0  # 질문 2회 청취 · 따로 준비 시간 없음
    lv = next(f for f in opic["fields"] if f["key"] == "level")
    assert lv["kind"] == "level" and len(lv["options"]) == 6 and lv["options"][0].startswith("1 · 10단어")
    toeic = next(k for k in kinds if k["key"] == "toeic")
    assert toeic["level_bands"]["IH"] == "140~150점" and toeic["levels"][-1] == "AH"


def test_start_validates(client, auth):
    assert client.post("/api/interviews", json={"kind": "nope"}, headers=auth).status_code == 422
    few = {**OPIC_SETUP, "leisure": "영화 보기", "hobby": "", "sport": "조깅", "travel": "국내 여행"}
    r = client.post("/api/interviews", json={"kind": "opic", "setup": few}, headers=auth)
    detail = r.json()["detail"]
    assert r.status_code == 422 and "설문 항목 12개 이상" in detail and "여가 활동 2개 이상" in detail and "취미·관심사" in detail
    # 목록에 없는 값은 버린다 · 1·2단계는 12문항
    d = run(client, auth, setup={**OPIC_FULL, "leisure": SURVEY["leisure"] + ", 우주여행", "level": interview.OPIC_SELF[1]})
    assert "우주여행" not in d["setup"]["leisure"] and d["mains"] == 12
    assert run(client, auth, setup=OPIC_FULL)["mains"] == 15


def test_opic_format_without_ai(client, auth):
    import random
    import re
    d = run(client, auth)
    t = d["turns"]
    assert d["by_ai"] is False and d["mains"] == 7 and t[0]["part"] == "자기소개" and t[0]["prep"] == 0
    plan = interview.OPIC.bank(OPIC_FULL, random.Random(1))
    assert [x["part"] for x in plan[1:4]] == ["묘사", "일상·습관", "경험"] and plan[1]["topic"] == plan[3]["topic"]  # 3콤보
    assert plan[7]["part"].startswith("돌발") and plan[10]["part"].startswith("롤플레이") and plan[14]["part"] == "어드밴스 · 사회 이슈"
    assert all(not re.search("[가-힣]", x["q"]) for x in plan)  # 영어 질문에 한글이 끼지 않는다
    iid = d["id"]
    for i in range(7):
        text = LONG_EN if i % 2 == 0 else ("um I like like movies" if i == 1 else "")
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": text, "sec": 60}, headers=auth).json()
    assert d["status"] == "answered" and len(d["turns"]) == 7  # 짧은 연습은 난이도 재조정 없이 끝
    assert client.post(f"/api/interviews/{iid}/answers", json={"text": "x"}, headers=auth).status_code == 409
    d = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()
    rep = d["report"]
    assert d["status"] == "done" and rep["by_ai"] is False and rep["level"] in interview.OPIC.levels
    assert rep["metrics"]["skipped"] == 2 and rep["metrics"]["fillers"] >= 2 and rep["metrics"]["rate_unit"] == "단어/분"
    assert any("답하지 않은 질문" in x for x in rep["improve"]) and len(rep["per"]) == 7
    rows = client.get("/api/interviews", headers=auth).json()
    assert rows[0]["id"] == iid and rows[0]["level"] == rep["level"]


def test_opic_difficulty_readjustment(client, auth):
    d = run(client, auth, setup=OPIC_FULL)
    iid = d["id"]
    for _ in range(7):
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 90}, headers=auth).json()
    assert d["status"] == "adjust" and d["current"] is None  # 7번 뒤 '쉬운 질문 / 비슷한 질문 / 어려운 질문'
    assert client.post(f"/api/interviews/{iid}/answers", json={"text": "x"}, headers=auth).status_code == 409
    assert client.post(f"/api/interviews/{iid}/adjust", json={"choice": "wrong"}, headers=auth).status_code == 422
    d = client.post(f"/api/interviews/{iid}/adjust", json={"choice": "harder"}, headers=auth).json()
    assert d["status"] == "active" and d["setup"]["adjusted"] == "harder" and d["setup"]["level2"] == "6"
    assert len(d["turns"]) == 8 and d["turns"][7]["part"].startswith("돌발")
    assert client.post(f"/api/interviews/{iid}/adjust", json={"choice": "same"}, headers=auth).status_code == 409
    while d["status"] == "active":
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 90}, headers=auth).json()
    assert d["status"] == "answered" and len(d["turns"]) == 15 and d["turns"][-1]["part"] == "어드밴스 · 사회 이슈"
    # 3단계에서 '쉬운 질문' 으로 내려가면 2차 세션은 2단계 기준
    d = run(client, auth, setup={**OPIC_FULL, "level": interview.OPIC_SELF[2]})
    for _ in range(7):
        d = client.post(f"/api/interviews/{d['id']}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    d = client.post(f"/api/interviews/{d['id']}/adjust", json={"choice": "easier"}, headers=auth).json()
    assert d["setup"]["level2"] == "2" and d["mains"] == 15


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
    d = run(client, auth, kind="job", setup={"job": "백엔드 개발자"})
    assert d["by_ai"] is True and d["turns"][0]["q"] == "AI question 1?"
    iid = d["id"]
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    assert d["turns"][-1]["q"] == "AI question 2?"  # 첫 질문(자기소개) 뒤에는 꼬리질문 없음
    d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    assert d["turns"][-1]["follow"] is True and d["turns"][-1]["part"] == "꼬리질문"  # 두 번째부터 꼬리질문
    while d["status"] == "active":
        d = client.post(f"/api/interviews/{iid}/answers", json={"text": LONG_EN, "sec": 60}, headers=auth).json()
    follows = [t for t in d["turns"] if t["follow"]]
    assert len(follows) == interview.JOB.follow_ups and len(d["turns"]) == 6 + len(follows)
    d = client.post(f"/api/interviews/{iid}/finish", headers=auth).json()
    rep = d["report"]
    assert rep["by_ai"] and rep["score"] == 78 and len(rep["items"]) == len(d["turns"])
    assert llm.calls.count("Plan") == 1 and llm.calls.count("Report") == 1
    # OPIc 은 실제 시험처럼 정해진 구성 — AI 는 질문을 만들지 않고 평가만
    llm.calls.clear()
    d = run(client, auth)
    assert d["by_ai"] is False and "Plan" not in llm.calls


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
