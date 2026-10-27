"""기출 업로드 → AI 분석 → 기출 기반 생성, 주관식, 사용자별 공개 범위, 화면 동기화."""

import io
import threading
from contextlib import nullcontext

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from education.api.routers import projects as projects_router
from education.db import models as m
from education.db.session import session_factory
from education.services import materials
from education.services.generator import GeneratedProblem, GeneratedShort, ShortVerdict, Verdict
from education.services.llm import LLMResult, Usage
from education.services.materials import Extraction, ExtractedProblem

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class QueueLLM:
    """스키마별로 정해 둔 응답을 차례로 돌려주는 가짜 LLM."""

    def __init__(self, **queues):
        self.queues = {k: list(v) for k, v in queues.items()}
        self.lock = threading.Lock()
        self.files_seen = []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        with self.lock:
            self.files_seen.append(files)
            item = self.queues[schema.__name__].pop(0)
        return LLMResult(data=item, usage=Usage(model="gpt-6.1-sol", input_tokens=100, output_tokens=100))


def extracted(**kw):
    base = dict(number=1, stem="$\\log_2 32$의 값은?", choices=["3", "4", "5", "6", "7"], answer="3",
                concept_id="math.math1.exp_log.log_properties", difficulty=2, needs_figure=False)
    return ExtractedProblem(**{**base, **kw})


@pytest.fixture(autouse=True)
def tmp_uploads(monkeypatch, tmp_path):
    """업로드 파일은 임시 폴더에 (프로젝트 폴더를 더럽히지 않게)."""
    monkeypatch.setattr(materials, "UPLOAD_DIR", tmp_path)


@pytest.fixture
def background_db(db):
    """업로드 후 백그라운드 분석도 테스트 DB 세션을 쓰게 한다."""
    from education.api.main import app
    app.dependency_overrides[session_factory] = lambda: (lambda: nullcontext(db))
    yield
    app.dependency_overrides.pop(session_factory, None)


def make_project(client, auth, **kw):
    body = {"name": "수학I 기말", "subject_id": "math.math1", **kw}
    r = client.post("/api/projects", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, auth, pid, data=PNG, ctype="image/png", rights="true"):
    return client.post(f"/api/projects/{pid}/materials", headers=auth,
                       files={"file": ("시험지.png", data, ctype)}, data={"rights_confirmed": rights})


@pytest.fixture
def uploaded(client, auth, monkeypatch, background_db):
    """정답 있는 문제 1개 + 정답 없는 문제 1개 + 그림 필요 문제 1개를 뽑아 낸 업로드."""
    llm = QueueLLM(Extraction=[Extraction(problems=[
        extracted(),
        extracted(number=2, stem="$\\log_3 81$의 값은?", answer=None),
        extracted(number=3, stem="그래프를 보고 답하시오 [그림: 로그함수]", needs_figure=True),
    ])])
    monkeypatch.setattr(materials, "get_llm", lambda: llm)
    pid = make_project(client, auth)
    r = upload(client, auth, pid)
    assert r.status_code == 201, r.text
    return pid, r.json()["id"], llm


# ---------- 프로젝트 설정 ----------
def test_project_question_type(client, auth):
    pid = make_project(client, auth, question_type="short_answer")
    assert client.get(f"/api/projects/{pid}", headers=auth).json()["project"]["question_type"] == "short_answer"
    bad = client.post("/api/projects", json={"name": "x", "subject_id": "math.math1", "question_type": "essay"}, headers=auth)
    assert bad.status_code == 422


# ---------- 업로드 검증 ----------
def test_upload_requires_rights_and_valid_file(client, auth, background_db):
    pid = make_project(client, auth)
    assert upload(client, auth, pid, rights="false").status_code == 422
    assert "PDF 또는 사진" in upload(client, auth, pid, data=b"hi", ctype="text/plain").json()["detail"]
    writer = PdfWriter()
    for _ in range(31):
        writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    assert "30쪽" in upload(client, auth, pid, data=buf.getvalue(), ctype="application/pdf").json()["detail"]


def test_upload_without_ai_marks_failed(client, auth, monkeypatch, background_db):
    monkeypatch.setattr(materials, "get_llm", lambda: None)
    pid = make_project(client, auth)
    upload(client, auth, pid)
    m_ = client.get(f"/api/projects/{pid}/materials", headers=auth).json()[0]
    assert m_["status"] == "failed" and "AI" in m_["error"]


# ---------- 분석 결과 ----------
def test_extraction_creates_private_past_problems(client, auth, uploaded, new_user, db):
    pid, material_id, llm = uploaded
    assert llm.files_seen[0][0].mime == "image/png"  # 파일이 AI 로 전달됨
    mat = client.get(f"/api/projects/{pid}/materials", headers=auth).json()[0]
    assert mat["status"] == "ready" and mat["problem_count"] == 3

    past = client.get(f"/api/projects/{pid}/past-problems", headers=auth).json()
    assert [(p["number"], p["has_answer"], p["needs_figure"]) for p in past] == [(1, True, False), (2, False, False), (3, True, True)]
    assert all("answer" not in p for p in past)

    servable, no_answer, figure = (p["id"] for p in past)
    assert client.post("/api/attempts", json={"problem_id": servable, "answer": "3"}, headers=auth).json()["correct"]
    assert client.post("/api/attempts", json={"problem_id": no_answer, "answer": "4"}, headers=auth).status_code == 404

    # 다른 사용자에게는 존재하지 않는 것처럼
    other = new_user()
    assert client.get(f"/api/problems/{servable}", headers=other).status_code == 404
    assert client.post("/api/attempts", json={"problem_id": servable, "answer": "3"}, headers=other).status_code == 404
    assert client.put(f"/api/saved/{servable}", headers=other).status_code == 404
    assert servable not in {p["id"] for p in client.get("/api/sync", headers=other).json()["problems"]}


def test_delete_material_removes_file_and_past_problems(client, auth, uploaded, db):
    pid, material_id, _ = uploaded
    path = materials.UPLOAD_DIR / db.get(m.Material, material_id).storage_path
    assert path.exists()
    assert client.delete(f"/api/materials/{material_id}", headers=auth).status_code == 204
    assert not path.exists()
    assert client.get(f"/api/projects/{pid}/past-problems", headers=auth).json() == []


# ---------- 기출 기반 생성 ----------
def gen_mc(stem="새 문제"):
    return GeneratedProblem(stem=stem, choices=["1", "2", "3", "4", "5"], answer="2", solution="풀이", traps=[])


def test_generate_from_past_uses_exemplars_and_level(client, auth, uploaded, monkeypatch, new_user, db):
    pid, _, _ = uploaded
    llm = QueueLLM(GeneratedProblem=[gen_mc("A"), gen_mc("B")],
                   Verdict=[Verdict(answer="2", work="", well_posed=True, issues=[])] * 2)
    monkeypatch.setattr(projects_router, "get_llm", lambda: llm)
    r = client.post(f"/api/projects/{pid}/generate", json={"level": "harder", "count": 2}, headers=auth)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["project_id"] == pid and "어렵게" in s["title"]
    problems = s["messages"][1]["problems"]
    assert len(problems) == 2
    row = db.get(m.Problem, problems[0]["id"])
    assert row.difficulty == 3  # 기출 난이도 2 → 어렵게 +1
    assert row.owner_user_id is not None  # 기출 기반 문제는 올린 사람만
    assert len(row.generation_meta["exemplar_ids"]) == 3
    other = new_user()
    assert client.get(f"/api/problems/{row.id}", headers=other).status_code == 404


def test_generate_without_ai(client, auth, monkeypatch):
    monkeypatch.setattr(projects_router, "get_llm", lambda: None)
    pid = make_project(client, auth)
    assert client.post(f"/api/projects/{pid}/generate", json={}, headers=auth).status_code == 503


def test_short_answer_project(client, auth, monkeypatch):
    pid = make_project(client, auth, question_type="short_answer")
    llm = QueueLLM(GeneratedShort=[GeneratedShort(stem="$2^3 - 1$의 값은?", answer=7, solution="8 - 1 = 7", traps=[])],
                   ShortVerdict=[ShortVerdict(answer=7, work="", well_posed=True, issues=[])])
    monkeypatch.setattr(projects_router, "get_llm", lambda: llm)
    s = client.post(f"/api/projects/{pid}/generate", json={"count": 1}, headers=auth).json()
    p = s["messages"][1]["problems"][0]
    assert p["problem_type"] == "short_answer" and p["choices"] is None
    r = client.post("/api/attempts", json={"problem_id": p["id"], "answer": " 007 "}, headers=auth).json()
    assert r["correct"] is True and r["answer"] == "7"


# ---------- 화면 동기화 ----------
def test_sync_shape_and_answer_reveal(client, auth):
    data = client.get("/api/sync", headers=auth).json()
    assert set(data) >= {"user", "projects", "sessions", "attempts", "wrongNotes", "cards", "savedProblemIds", "problems"}
    log = next(p for p in data["problems"] if p["id"] == "pb_log")
    assert log["answer"] is None and log["solution"] is None  # 안 푼 문제는 정답 숨김
    client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "1"}, headers=auth)
    data = client.get("/api/sync", headers=auth).json()
    log = next(p for p in data["problems"] if p["id"] == "pb_log")
    assert log["answer"] == "3" and data["attempts"][0]["correct"] is False
    assert isinstance(data["attempts"][0]["at"], int)  # epoch 밀리초
