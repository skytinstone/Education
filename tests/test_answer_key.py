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
