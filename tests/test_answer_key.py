"""정답지 — 정답표가 있는 문항은 AI 풀이와 맞춰 보고, 없는 문항은 두 번 풀어 비교한다."""

from sqlalchemy import select

from education.api.routers import projects as projects_router
from education.db import models as m
from education.schemas import VerificationStatus
from education.services import answer_key, materials
from education.services.answer_key import CheckBatch, Checked, SolveBatch, Solved
from education.services.materials import Extraction
from test_materials import QueueLLM, background_db, extracted, make_project, tmp_uploads, upload  # noqa: F401 (픽스처)


def setup_material(client, auth, monkeypatch):
    llm = QueueLLM(Extraction=[Extraction(problems=[
        extracted(number=2, stem="2번 문제", answer="2"),
        extracted(number=1, stem="1번 문제", answer="3"),
        extracted(number=3, stem="3번 문제", answer=None),
        extracted(number=4, stem="4번 문제", answer=None),
    ])])
    monkeypatch.setattr(materials, "get_llm", lambda: llm)
    pid = make_project(client, auth)
    mid = upload(client, auth, pid).json()["id"]
    return pid, mid


def solve_llm():
    # 번호순(1,2,3,4)으로 묶여 풀린다: idx 1=1번, 2=2번, 3=3번, 4=4번
    return QueueLLM(
        SolveBatch=[SolveBatch(items=[
            Solved(idx=1, answer="③", solution="1) 로그의 성질을 써요.\n2) 답은 $5$예요."),
            Solved(idx=2, answer="4번", solution="1) 풀이"),
            Solved(idx=3, answer="5", solution="1) 풀이"),
            Solved(idx=4, answer="1", solution="1) 풀이"),
        ])],
        CheckBatch=[CheckBatch(items=[Checked(idx=3, answer="⑤"), Checked(idx=4, answer="2")])],
    )


def test_answer_key_statuses_and_practice_use(client, auth, monkeypatch, background_db, db):
    _, mid = setup_material(client, auth, monkeypatch)
    llm = solve_llm()
    monkeypatch.setattr(answer_key, "get_llm", lambda: llm)
    monkeypatch.setattr(projects_router, "get_llm", lambda: llm)

    r = client.post(f"/api/materials/{mid}/answer-key", headers=auth)
    assert r.status_code == 202 and r.json()["answer_key_status"] == "running"

    key = client.get(f"/api/materials/{mid}/answer-key", headers=auth).json()
    assert key["material"]["answer_key_status"] == "done"
    items = key["items"]
    assert [i["number"] for i in items] == [1, 2, 3, 4]  # 번호순
    assert [i["status"] for i in items] == ["confirmed", "conflict", "verified", "uncertain"]
    assert [i["answer"] for i in items] == ["3", "2", "5", "1"]          # 정답표 답 우선, 없으면 AI 답
    assert items[1]["ai_answer"] == "4" and items[1]["sheet_answer"] == "2"
    assert "로그의 성질" in items[0]["solution"]
    assert key["counts"]["conflict"] == 1 and key["counts"]["uncertain"] == 1

    # 확실한 문항만 학생 연습에 쓴다 (정답표와 다르거나 확인이 필요한 문항은 뺌)
    by_no = {p.generation_meta["number"]: p for p in db.scalars(select(m.Problem).where(m.Problem.material_id == mid))}
    assert by_no[1].verification == VerificationStatus.VERIFIED
    assert by_no[2].verification == VerificationStatus.PENDING
    assert by_no[3].verification == VerificationStatus.VERIFIED and by_no[3].answer == "5"
    assert by_no[4].verification == VerificationStatus.PENDING and by_no[4].answer == ""
    # 정답 없는 문항만 두 번째 AI 가 다시 푼다
    assert len(llm.queues["CheckBatch"]) == 0
    note = db.scalar(select(m.Notification).where(m.Notification.title.startswith("정답지 완성")))
    assert "2문항" in note.body and note.link == f"#/answer-key/{mid}"


def test_rebuilding_keeps_original_sheet_answers(client, auth, monkeypatch, background_db):
    _, mid = setup_material(client, auth, monkeypatch)
    for _ in range(2):
        llm = solve_llm()
        monkeypatch.setattr(answer_key, "get_llm", lambda llm=llm: llm)
        monkeypatch.setattr(projects_router, "get_llm", lambda llm=llm: llm)
        assert client.post(f"/api/materials/{mid}/answer-key", headers=auth).status_code == 202
    items = client.get(f"/api/materials/{mid}/answer-key", headers=auth).json()["items"]
    # 두 번째에도 3번은 '정답표'가 아니라 AI 가 채운 답 → 다시 두 번 풀어 검산한다
    assert [i["status"] for i in items] == ["confirmed", "conflict", "verified", "uncertain"]
    assert items[2]["sheet_answer"] == ""


def test_answer_key_guards(client, auth, new_user, monkeypatch, background_db, db):
    _, mid = setup_material(client, auth, monkeypatch)
    monkeypatch.setattr(projects_router, "get_llm", lambda: None)
    assert client.post(f"/api/materials/{mid}/answer-key", headers=auth).status_code == 503
    assert client.get(f"/api/materials/{mid}/answer-key", headers=new_user()).status_code == 404  # 남의 자료
    monkeypatch.setattr(projects_router, "get_llm", lambda: object())
    db.get(m.Material, mid).answer_key_status = "running"
    db.flush()
    assert client.post(f"/api/materials/{mid}/answer-key", headers=auth).status_code == 409


def test_normalizes_answers():
    p = m.Problem(choices=["a", "b", "c", "d", "e"])
    assert answer_key.normalize(p, "③") == "3" and answer_key.normalize(p, "정답은 4번") == "4" and answer_key.normalize(p, "9") == ""
    s = m.Problem(choices=None)
    assert answer_key.same(s, "1/2", "0.5") and answer_key.same(s, "√2", "√ 2") and not answer_key.same(s, "3", "4")


# ---------- 정답 파일 ↔ 문제지 1:1 ----------
from education.services.materials import AnswerEntry, AnswerSheet  # noqa: E402


def upload_answers(client, auth, pid, mid, entries, monkeypatch):
    llm = QueueLLM(AnswerSheet=[AnswerSheet(entries=entries)])
    monkeypatch.setattr(materials, "get_llm", lambda: llm)
    return client.post(f"/api/projects/{pid}/materials", headers=auth, files={"file": ("정답.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
                       data={"rights_confirmed": "true", "kind": "answer_sheet", "answer_for": mid})


def test_answer_file_maps_one_to_one_by_number(client, auth, monkeypatch, background_db, db):
    pid, mid = setup_material(client, auth, monkeypatch)
    r = upload_answers(client, auth, pid, mid, [
        AnswerEntry(number=1, answer="①", explanation="정답 파일 해설: $x=1$"),
        AnswerEntry(number=3, answer="⑤", explanation=None),
        AnswerEntry(number=7, answer="2", explanation=None),   # 문제지에 없는 번호
    ], monkeypatch)
    assert r.status_code == 201, r.text
    sheet = client.get(f"/api/projects/{pid}/materials", headers=auth).json()[-1]
    assert sheet["kind"] == "answer_sheet" and sheet["answer_for_id"] == mid and sheet["status"] == "ready"
    assert sheet["answer_map"] == {"matched": 2, "total": 4, "missing": [2, 4], "extra": [7]}

    rows = {r.number: r for r in db.scalars(select(m.ProblemAnswer).where(m.ProblemAnswer.material_id == mid))}
    assert len(rows) == 4                                   # 문항 하나에 정답 행 하나
    assert rows[1].sheet_answer == "1" and rows[1].printed_answer == "3" and rows[1].sheet_explanation.startswith("정답 파일")
    assert rows[3].sheet_answer == "5" and str(rows[3].sheet_material_id) == sheet["id"]
    p3 = db.get(m.Problem, rows[3].problem_id)
    assert p3.answer == "5" and p3.verification == VerificationStatus.VERIFIED   # 정답이 생겨 연습에 쓸 수 있다

    key = client.get(f"/api/materials/{mid}/answer-key", headers=auth).json()
    assert key["answer_file"]["filename"] == "정답.png"
    assert [(i["number"], i["answer"], i["from_answer_file"]) for i in key["items"]] == [(1, "1", True), (2, "2", False), (3, "5", True), (4, "", False)]

    # 정답 파일은 문제지 하나에 하나 — 새로 올리면 교체된다
    upload_answers(client, auth, pid, mid, [AnswerEntry(number=4, answer="2", explanation=None)], monkeypatch)
    sheets = [x for x in client.get(f"/api/projects/{pid}/materials", headers=auth).json() if x["kind"] == "answer_sheet"]
    assert len(sheets) == 1 and sheets[0]["answer_map"]["matched"] == 1
    db.expire_all()
    rows = {r.number: r for r in db.scalars(select(m.ProblemAnswer).where(m.ProblemAnswer.material_id == mid))}
    assert rows[1].sheet_answer == "3" and rows[3].sheet_answer == "" and rows[4].sheet_answer == "2"  # 예전 파일 정답은 거둠

    # 정답 파일을 지우면 문제지에 인쇄돼 있던 정답으로 돌아간다
    assert client.delete(f"/api/materials/{sheets[0]['id']}", headers=auth).status_code == 204
    db.expire_all()
    rows = {r.number: r for r in db.scalars(select(m.ProblemAnswer).where(m.ProblemAnswer.material_id == mid))}
    assert rows[4].sheet_answer == "" and rows[1].sheet_answer == "3"


def test_answer_file_needs_a_ready_problem_sheet(client, auth, monkeypatch, background_db, db):
    pid, mid = setup_material(client, auth, monkeypatch)
    no_target = client.post(f"/api/projects/{pid}/materials", headers=auth, files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
                            data={"rights_confirmed": "true", "kind": "answer_sheet"})
    assert no_target.status_code == 422
    db.get(m.Material, mid).status = "extracting"
    db.flush()
    assert upload_answers(client, auth, pid, mid, [], monkeypatch).status_code == 409


def test_deleting_problem_sheet_removes_its_answer_file(client, auth, monkeypatch, background_db, db):
    pid, mid = setup_material(client, auth, monkeypatch)
    upload_answers(client, auth, pid, mid, [AnswerEntry(number=1, answer="1", explanation=None)], monkeypatch)
    assert client.delete(f"/api/materials/{mid}", headers=auth).status_code == 204
    assert client.get(f"/api/projects/{pid}/materials", headers=auth).json() == []


def test_project_workspace_merges_problems_and_answers(client, auth, new_user, monkeypatch, background_db):
    pid, mid = setup_material(client, auth, monkeypatch)
    upload_answers(client, auth, pid, mid, [AnswerEntry(number=3, answer="④", explanation=None)], monkeypatch)
    w = client.get(f"/api/projects/{pid}/workspace", headers=auth).json()
    assert [x["kind"] for x in w["materials"]] == ["past_exam", "answer_sheet"]
    rows = {x["number"]: x for x in w["problems"]}
    assert [x["number"] for x in w["problems"]] == [1, 2, 3, 4]            # 자료별 번호순
    assert (rows[1]["answer"], rows[1]["answer_source"]) == ("3", "printed")  # 시험지에 인쇄된 정답
    assert (rows[3]["answer"], rows[3]["answer_source"]) == ("4", "file")     # 정답 파일에서 1:1
    assert rows[4]["answer_source"] is None and rows[4]["answer"] == ""
    assert client.get(f"/api/projects/{pid}/workspace", headers=new_user()).status_code == 404


def test_ask_about_selected_part_uses_problem_context(client, auth, new_user, monkeypatch, background_db, db):
    """정답지에서 드래그한 부분을 인용해 묻기: 문항·정답·해설과 인용·이전 대화를 AI 에게 넘기고 풀이 형식으로 답한다."""
    from education.services.explain import Check, Explanation, Step
    from education.services.llm import LLMResult, Usage

    _, mid = setup_material(client, auth, monkeypatch)
    llm = solve_llm()
    monkeypatch.setattr(answer_key, "get_llm", lambda: llm)
    monkeypatch.setattr(projects_router, "get_llm", lambda: llm)
    client.post(f"/api/materials/{mid}/answer-key", headers=auth)
    first = client.get(f"/api/materials/{mid}/answer-key", headers=auth).json()["items"][0]

    prompts = []

    class AskLLM:
        def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000):
            assert schema is Explanation and "인용" in instructions
            prompts.append(prompt)
            return LLMResult(data=Explanation(summary="로그를 나눠 써요.", principle="", steps=[Step(title="쪼개기", text="$5$예요.", math="")],
                                              result="5", graph=None, check=Check(kind="none", expr="", answer="", a="", b="")),
                             usage=Usage(model="gpt-6.1-sol", input_tokens=10, output_tokens=10))

    monkeypatch.setattr(projects_router, "get_llm", lambda: AskLLM())
    body = {"problem_id": first["id"], "question": "더 자세히 설명해 줘", "quote": "로그의 성질을 써요",
            "history": [{"q": "왜 5예요?", "a": "32 는 2의 5제곱이에요."}]}
    r = client.post(f"/api/materials/{mid}/ask", headers=auth, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["explanation"]["summary"] == "로그를 나눠 써요." and r.json()["explanation"]["check"]["status"] == "unchecked"
    p = prompts[0]
    assert "1번 문항: 1번 문제" in p and "로그의 성질을 써요" in p and "왜 5예요?" in p and "더 자세히 설명해 줘" in p
    assert db.scalar(select(m.LLMCall).where(m.LLMCall.purpose == "ask")) is not None

    # 다른 자료의 문항, 남의 자료는 묻지 못한다
    assert client.post(f"/api/materials/{mid}/ask", headers=auth, json={**body, "problem_id": "nope"}).status_code == 404
    other = new_user()
    assert client.post(f"/api/materials/{mid}/ask", headers=other, json=body).status_code == 404
