"""책 검색 — 교재 이름이나 ISBN 으로 서지 정보(제목·저자·출판사·연도·ISBN·표지)를 찾는다. 모두 선택 기능이다.

책 본문·문제는 저작권 때문에 어떤 API 도 주지 않고, 우리도 가져오지 않는다. 여기서는 서지 정보만 쓴다.
찾는 순서 (앞에서 찾으면 그걸 먼저 보여 준다):
  1. 카카오 책 검색 — KAKAO_REST_API_KEY (간편 로그인용 키를 그대로 씀). 국내 책에 강하다
  2. Google Books — GOOGLE_BOOKS_API_KEY 가 있을 때만 (키 없이 부르면 사용량 한도에 금방 막힌다)
  3. Open Library — 키 없이. 영어 원서 제목 검색용
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import httpx2
from pydantic import BaseModel

from education.config import get_settings

log = logging.getLogger(__name__)
UA = {"User-Agent": "Eureka/1.0 (https://eurekai.cloud)"}


class Book(BaseModel):
    title: str
    authors: list[str] = []
    publisher: str = ""
    year: str = ""
    isbn: str | None = None  # ISBN-13 (없으면 ISBN-10)
    thumbnail: str | None = None
    source: str  # kakao | google | openlibrary


def isbn_of(text: str) -> str | None:
    """입력이 ISBN 이면 숫자만 (하이픈·공백 무시), 아니면 None."""
    digits = re.sub(r"[\s-]", "", text)
    return digits.upper() if re.fullmatch(r"(97[89])?\d{9}[\dXx]", digits) else None


def _pick_isbn(values: list[str]) -> str | None:
    clean = [re.sub(r"[^\dXx]", "", v) for v in values if v]
    return next((v for v in clean if len(v) == 13), None) or next((v for v in clean if len(v) == 10), None)


# ---------- 공급자별 응답 → Book ----------
def parse_kakao(data: dict) -> list[Book]:
    out = []
    for d in data.get("documents", []):
        out.append(Book(title=d.get("title", "").strip(), authors=d.get("authors") or [], publisher=d.get("publisher") or "",
                        year=(d.get("datetime") or "")[:4], isbn=_pick_isbn((d.get("isbn") or "").split()),
                        thumbnail=d.get("thumbnail") or None, source="kakao"))
    return [b for b in out if b.title]


def parse_google(data: dict) -> list[Book]:
    out = []
    for it in data.get("items", []):
        v = it.get("volumeInfo", {})
        title = v.get("title", "") + (f": {v['subtitle']}" if v.get("subtitle") else "")
        ids = [x.get("identifier", "") for x in v.get("industryIdentifiers", [])]
        out.append(Book(title=title.strip(), authors=v.get("authors") or [], publisher=v.get("publisher") or "",
                        year=(v.get("publishedDate") or "")[:4], isbn=_pick_isbn(ids),
                        thumbnail=(v.get("imageLinks") or {}).get("thumbnail"), source="google"))
    return [b for b in out if b.title]


def parse_openlibrary(data: dict) -> list[Book]:
    out = []
    for d in data.get("docs", []):
        cover = d.get("cover_i")
        out.append(Book(title=d.get("title", "").strip(), authors=(d.get("author_name") or [])[:3],
                        publisher=(d.get("publisher") or [""])[0], year=str(d.get("first_publish_year") or ""),
                        isbn=_pick_isbn(d.get("isbn") or []), source="openlibrary",
                        thumbnail=f"https://covers.openlibrary.org/b/id/{cover}-S.jpg" if cover else None))
    return [b for b in out if b.title]


# ---------- 검색 ----------
def _get(http: httpx2.Client, url: str, **kw) -> dict:
    res = http.get(url, **kw)
    res.raise_for_status()
    return res.json()


@lru_cache(maxsize=512)
def search(query: str, limit: int = 6) -> tuple[Book, ...]:
    s = get_settings()
    isbn = isbn_of(query)
    found: list[Book] = []
    with httpx2.Client(timeout=6, headers=UA) as http:
        tries = []
        if s.kakao_rest_api_key:
            tries.append(("kakao", lambda: parse_kakao(_get(
                http, "https://dapi.kakao.com/v3/search/book", headers={"Authorization": f"KakaoAK {s.kakao_rest_api_key}"},
                params={"query": isbn or query, "target": "isbn" if isbn else "title", "size": limit}))))
        if s.google_books_api_key:
            tries.append(("google", lambda: parse_google(_get(
                http, "https://www.googleapis.com/books/v1/volumes",
                params={"q": f"isbn:{isbn}" if isbn else query, "maxResults": limit, "printType": "books", "key": s.google_books_api_key}))))
        tries.append(("openlibrary", lambda: parse_openlibrary(_get(
            http, "https://openlibrary.org/search.json",
            params={"q": isbn or query, "limit": limit, "fields": "title,author_name,publisher,first_publish_year,isbn,cover_i"}))))
        for name, fetch in tries:
            try:
                found += fetch()
            except (httpx2.HTTPError, ValueError) as e:
                log.warning("책 검색 실패 (%s): %s", name, e)
            if len(found) >= limit:
                break
    seen, out = set(), []
    for b in found:  # 같은 책(ISBN 또는 제목+저자)은 한 번만
        key = b.isbn or (b.title.lower(), tuple(b.authors[:1]))
        if key not in seen:
            seen.add(key)
            out.append(b)
    return tuple(out[:limit])
