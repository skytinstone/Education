"""책 검색 — 교재 이름·ISBN 으로 서지 정보 (선택 기능, 책 내용은 가져오지 않음)."""

from fastapi import APIRouter

from education.api.deps import CurrentUser
from education.services import books

router = APIRouter(tags=["교재"])


@router.get("/books/search")
def search_books(q: str, user: CurrentUser) -> list[books.Book]:
    """교재 칸의 후보 — 제목이나 ISBN (두 글자 이상). 못 찾거나 검색이 막혀도 빈 목록 (교재 이름은 직접 적으면 된다)."""
    q = q.strip()
    return list(books.search(q[:100])) if len(q) >= 2 else []
