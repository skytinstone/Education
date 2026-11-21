"""대화 입력창 + 첨부: 올리기 → 메시지에 붙이기 → AI 가 자료를 읽고 풀이, 본인만 보기, 정리."""

import pytest
from sqlalchemy import select

from education.config import get_settings
from education.db import models as m
from education.services import chat_files, tutor
from education.services.explain import Check, Explanation, Step
from education.services.llm import LLMResult, Usage

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FileLLM:
    """첨부를 받았는지 기록하는 가짜 LLM."""

    def __init__(self):
        self.calls = []

    def structured(self, *, model, effort, instructions, prompt, schema, max_output_tokens=16000, files=None):
        self.calls.append({"instructions": instructions, "prompt": prompt, "files": files})
        data = Explanation(summary="사진 속 문제의 답은 $3$ 이에요.", principle="로그의 정의", result="3", graph=None,
                           steps=[Step(title="읽기", text="$\\log_2 8$ 이에요.", math="\\log_2 8 = 3")],
                           check=Check(kind="none", expr="", answer="", a="", b=""))
        return LLMResult(data=data, usage=Usage(model="gpt-6.1-sol", input_tokens=900, output_tokens=300))


@pytest.fixture(autouse=True)
def tmp_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_files, "UPLOAD_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def llm(monkeypatch):
    fake = FileLLM()
    monkeypatch.setattr(tutor, "get_llm", lambda: fake)
    return fake


def upload(client, auth, data=PNG, name="문제.png", mime="image/png"):
    return client.post("/api/sessions/files", headers=auth, files={"file": (name, data, mime)})


def test_photo_is_read_by_ai_and_shown_on_message(client, auth, llm, tmp_uploads):
    r = upload(client, auth)
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["filename"] == "문제.png" and f["content_type"] == "image/png" and f["size_bytes"] == len(PNG)

    r = client.post("/api/sessions", headers=auth, json={"text": "이 문제 풀어 줘", "attachment_ids": [f["id"]]})
    assert r.status_code == 201, r.text
    detail = r.json()
    user_msg, ai_msg = detail["messages"]
    assert [a["id"] for a in user_msg["attachments"]] == [f["id"]]
    assert ai_msg["explanation"]["summary"].startswith("사진 속") and "첨부한 자료" in ai_msg["text"]
    call = llm.calls[0]
    assert call["files"][0].mime == "image/png" and call["files"][0].data == PNG
    assert "사진·PDF" in call["instructions"] and "문제.png" in call["prompt"]

    # 대화를 다시 열어도 첨부가 보이고, 파일을 받을 수 있다
    again = client.get(f"/api/sessions/{detail['id']}", headers=auth).json()
    assert again["messages"][0]["attachments"][0]["filename"] == "문제.png"
    r = client.get(f"/api/sessions/files/{f['id']}", headers=auth)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"

    # 앱을 다시 켤 때 받는 /sync 에도 첨부가 들어 있다
    synced = next(x for x in client.get("/api/sync", headers=auth).json()["sessions"] if x["id"] == detail["id"])
    assert synced["messages"][0]["files"] == [{"id": f["id"], "name": "문제.png", "mime": "image/png", "size": len(PNG)}]
    assert synced["messages"][1]["files"] == []

    # 이미 보낸 첨부는 다른 메시지에 다시 붙일 수 없다
    r = client.post(f"/api/sessions/{detail['id']}/messages", headers=auth, json={"text": "또", "attachment_ids": [f["id"]]})
    assert r.status_code == 422

    # 대화를 지우면 디스크 파일도 지운다
    assert list(tmp_uploads.rglob("*.png"))
    assert client.delete(f"/api/sessions/{detail['id']}", headers=auth).status_code == 204
    assert not list(tmp_uploads.rglob("*.png"))


def test_attachment_only_message_uses_default_text_and_file_title(client, auth, llm):
    f = upload(client, auth, name="수학 기출 3번.png").json()
    r = client.post("/api/sessions", headers=auth, json={"attachment_ids": [f["id"]]})
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "수학 기출 3번.png"
    assert r.json()["messages"][0]["text"] == "첨부한 자료를 보고 풀이해 줘"


def test_needs_text_or_attachment(client, auth):
    assert client.post("/api/sessions", headers=auth, json={"text": "   "}).status_code == 422


def test_files_are_private(client, auth, new_user, llm):
    f = upload(client, auth).json()
    other = new_user()
    assert client.get(f"/api/sessions/files/{f['id']}", headers=other).status_code == 404
    r = client.post("/api/sessions", headers=other, json={"text": "풀어 줘", "attachment_ids": [f["id"]]})
    assert r.status_code == 422
    assert client.delete(f"/api/sessions/files/{f['id']}", headers=other).status_code == 404


def test_rejects_wrong_type_and_too_many(client, auth, llm):
    r = upload(client, auth, data=b"hello", name="a.txt", mime="text/plain")
    assert r.status_code == 422 and "PDF" in r.json()["detail"]
    ids = [upload(client, auth).json()["id"] for _ in range(6)]
    r = client.post("/api/sessions", headers=auth, json={"text": "풀어 줘", "attachment_ids": ids})
    assert r.status_code == 422


def test_unsent_attachment_can_be_removed(client, auth, db, tmp_uploads):
    f = upload(client, auth).json()
    assert client.delete(f"/api/sessions/files/{f['id']}", headers=auth).status_code == 204
    assert db.scalar(select(m.ChatFile).where(m.ChatFile.id == f["id"])) is None
    assert not list(tmp_uploads.rglob("*.png"))


def test_without_ai_asks_to_type_the_problem(client, auth, monkeypatch):
    monkeypatch.setattr(tutor, "get_llm", lambda: None)
    f = upload(client, auth).json()
    r = client.post("/api/sessions", headers=auth, json={"text": "풀어 줘", "attachment_ids": [f["id"]]})
    assert r.status_code == 201 and "AI" in r.json()["messages"][1]["text"]


def test_drive_config_only_when_fully_set(client, auth, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_picker_api_key", None)
    monkeypatch.setattr(s, "google_app_id", "123")
    assert client.get("/api/sessions/drive-config", headers=auth).json() is None
    monkeypatch.setattr(s, "google_picker_api_key", "AIza-test")
    assert client.get("/api/sessions/drive-config", headers=auth).json() == {
        "client_id": "cid.apps.googleusercontent.com", "api_key": "AIza-test", "app_id": "123"}
