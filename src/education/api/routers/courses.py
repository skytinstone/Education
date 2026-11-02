"""코스 — 목록, 개념 트리, 출제 범위로 새 코스 만들기 (모두 공개)."""

from fastapi import APIRouter, HTTPException, status

from education.api.deps import DB, CurrentUser
from education.api.dto import ConceptOut, CourseDetail, CourseIn, CourseOut
from education.db import models as m
from education.services import courses
from education.services.llm import get_llm

router = APIRouter(prefix="/courses", tags=["코스"])


def _detail(db, user, course: m.Course) -> CourseDetail:
    concepts = courses.course_concepts(db, course.id)
    out = CourseOut.model_validate(course).model_copy(update={
        "units": sum(c.level == "unit" for c in concepts), "concepts": sum(c.level == "concept" for c in concepts),
        "mine": course.owner_user_id == user.id})
    return CourseDetail(course=out, concepts=[ConceptOut.model_validate(c) for c in concepts])


@router.get("")
def list_courses(user: CurrentUser, db: DB) -> list[CourseOut]:
    """모든 코스 — 공식 템플릿(수능 9과목 등)과 사용자들이 만든 코스."""
    return courses.list_courses(db, user)


@router.get("/{course_id}")
def get_course(course_id: str, user: CurrentUser, db: DB) -> CourseDetail:
    course = db.get(m.Course, course_id)
    if course is None:
        raise HTTPException(404, "코스를 찾을 수 없어요")
    return _detail(db, user, course)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_course(body: CourseIn, user: CurrentUser, db: DB) -> CourseDetail:
    """출제 범위(목차)를 붙여넣으면 AI 가 단원·개념 트리를 만든다 (30초~1분). 만든 코스는 모두에게 공개."""
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    try:
        course = courses.create_course(db, llm, user, title=body.title.strip(), scope_text=body.scope_text,
                                       exam=body.exam.strip(), level=body.level.strip(), textbook=body.textbook.strip(),
                                       textbook_isbn=body.textbook_isbn)
    except courses.CourseError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"코스를 만들지 못했어요. 잠시 후 다시 시도해 주세요 ({e})") from None
    return _detail(db, user, course)
