"""교재 연동 — 책 검색(선택, 서지 정보만), 교재 ISBN, 교재 페이지 업로드. 외부 API 는 부르지 않는다."""

import httpx2
import pytest
from sqlalchemy import select

from education.config import get_settings
from education.db import models as m
from education.services import books, materials, tutor
from education.services.materials import Extraction
from test_materials import PNG, QueueLLM, background_db, extracted, make_project  # noqa: F401 (background_db 는 fixture)

KAKAO = {"documents": [{"title": "수능특강 미적분", "authors": ["EBS"], "publisher": "한국교육방송공사",
                        "datetime": "2026-01-15T00:00:00.000+09:00", "isbn": "8954712345 9788954712345",
                        "thumbnail": "https://img/thumb.jpg"}]}
OPENLIBRARY = {"docs": [{"title": "Calculus, Early Transcendentals", "author_name": ["James Stewart"], "publisher": ["Cengage"],
                         "first_publish_year": 1991, "isbn": ["0534393217", "9780357533215"], "cover_i": 42}]}
GOOGLE = {"items": [{"volumeInfo": {"title": "Calculus", "subtitle": "Early Transcendentals", "authors": ["James Stewart"],
                                    "publishedDate": "2020-01-01", "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780357533215"}]}}]}


def test_parsers_and_isbn():
    k = books.parse_kakao(KAKAO)[0]
    assert (k.title, k.isbn, k.year, k.source) == ("수능특강 미적분", "9788954712345", "2026", "kakao")
    o = books.parse_openlibrary(OPENLIBRARY)[0]
    assert o.isbn == "9780357533215" and o.thumbnail.endswith("/42-S.jpg")
    g = books.parse_google(GOOGLE)[0]
    assert g.title == "Calculus: Early Transcendentals" and g.isbn == "9780357533215"
    assert books.isbn_of("978-0-357-53321-5") == "9780357533215" and books.isbn_of("수능특강") is None


class FakeHTTP:
    """URL 별로 정해 둔 응답 (예외면 실패)."""
    calls: list = []

    def __init__(self, routes):
        self.routes = routes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, headers=None):
        FakeHTTP.calls.append((url, params, headers))
        body = next(v for k, v in self.routes.items() if k in url)
        if isinstance(body, Exception):
            raise body
        return httpx2.Response(200, json=body, request=httpx2.Request("GET", url))


@pytest.fixture
def http(monkeypatch):
    books.search.cache_clear()
    FakeHTTP.calls = []

    def use(routes, kakao_key="kakao-key"):
        monkeypatch.setattr(get_settings(), "kakao_rest_api_key", kakao_key)
        monkeypatch.setattr(get_settings(), "google_books_api_key", None)
        monkeypatch.setattr(books.httpx2, "Client", lambda **kw: FakeHTTP(routes))
    yield use
    books.search.cache_clear()


def test_search_kakao_first_then_openlibrary(client, auth, http):
    http({"dapi.kakao.com": KAKAO, "openlibrary.org": OPENLIBRARY})
    r = client.get("/api/books/search", params={"q": "수능특강"}, headers=auth).json()
    assert [b["source"] for b in r] == ["kakao", "openlibrary"]
    url, params, headers = FakeHTTP.calls[0]
    assert params["target"] == "title" and headers["Authorization"] == "KakaoAK kakao-key"


def test_search_by_isbn_and_fallback(client, auth, http):
    http({"dapi.kakao.com": httpx2.ConnectError("down"), "openlibrary.org": OPENLIBRARY})
    r = client.get("/api/books/search", params={"q": "978-0357-533215"}, headers=auth).json()
    assert r[0]["isbn"] == "9780357533215"  # 카카오가 안 돼도 다른 곳에서
    assert FakeHTTP.calls[0][1] == {"query": "9780357533215", "target": "isbn", "size": 6}
    assert client.get("/api/books/search", params={"q": "수"}, headers=auth).json() == []  # 두 글자부터
    assert client.get("/api/books/search", params={"q": "수능"}).status_code == 401


def test_search_without_kakao_key_and_dedupe(client, auth, http):
    http({"openlibrary.org": {"docs": OPENLIBRARY["docs"] * 2}}, kakao_key=None)
    r = client.get("/api/books/search", params={"q": "stewart calculus"}, headers=auth).json()
    assert len(r) == 1 and all("dapi.kakao.com" not in c[0] for c in FakeHTTP.calls)


def test_textbook_isbn_is_optional_and_reaches_ai(client, auth, db):
    plain = client.post("/api/projects", json={"name": "a", "subject_id": "math.calculus", "textbook": "쎈 미적분"}, headers=auth).json()
    assert plain["textbook_isbn"] is None  # ISBN 없이도 된다
    pid = client.post("/api/projects", json={"name": "b", "subject_id": "math.calculus", "textbook": "수능특강 미적분",
                                              "textbook_isbn": "9788954712345"}, headers=auth).json()["id"]
    project = db.get(m.Project, __import__("uuid").UUID(pid))
    assert tutor.textbook_label(project) == "수능특강 미적분 (ISBN 9788954712345)"
    client.patch(f"/api/projects/{pid}", json={"textbook_isbn": None}, headers=auth)
    db.refresh(project)
    assert project.textbook_isbn is None and tutor.textbook_label(project) == "수능특강 미적분"
    assert client.get("/api/sync", headers=auth).json()["projects"][-1]["textbookIsbn"] in (None, "9788954712345")


def test_textbook_page_upload(client, auth, monkeypatch, background_db, db, tmp_path):
    monkeypatch.setattr(materials, "UPLOAD_DIR", tmp_path)
    llm = QueueLLM(Extraction=[Extraction(problems=[extracted(), extracted(number=2, stem="예제 2", answer=None)])])
    prompts = []
    real = llm.structured
    monkeypatch.setattr(llm, "structured", lambda **kw: (prompts.append(kw["prompt"]), real(**kw))[1])
    monkeypatch.setattr(materials, "get_llm", lambda: llm)
    pid = make_project(client, auth)
    r = client.post(f"/api/projects/{pid}/materials", headers=auth, files={"file": ("교재 p.120.png", PNG, "image/png")},
                    data={"rights_confirmed": "true", "kind": "textbook"})
    assert r.status_code == 201 and r.json()["kind"] == "textbook"
    assert "교재 페이지" in prompts[0] and "예제·연습문제" in prompts[0]
    sources = set(db.scalars(select(m.Problem.source).where(m.Problem.material_id == __import__("uuid").UUID(r.json()["id"]))))
    assert sources == {"textbook"}
    note = client.get("/api/notifications", headers=auth).json()["items"][0]
    assert note["title"].startswith("교재 분석 완료")
    bad = client.post(f"/api/projects/{pid}/materials", headers=auth, files={"file": ("x.png", PNG, "image/png")},
                      data={"rights_confirmed": "true", "kind": "novel"})
    assert bad.status_code == 422
