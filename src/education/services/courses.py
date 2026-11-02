"""코스 만들기 — 사용자가 붙여넣은 출제 범위(목차)를 AI 가 '단원 → 개념' 트리로 정리한다.

책 내용은 읽지 않는다. 장·절 제목(출제 범위)은 주제를 나열한 사실 정보이고, 개념 이름은 그 분야의 일반 지식으로 붙인다.
만든 코스는 모두에게 공개된다 (같은 시험을 준비하는 사람이 함께 쓴다).
"""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.api.dto import CourseOut

from education.config import get_settings
from education.db import models as m
from education.services.llm import LLM, LLMError

DOMAINS = ("math", "physics", "chemistry", "biology", "earth_science", "english", "korean", "social", "history",
           "economics", "accounting", "law", "computer", "medicine", "language", "general")


class ConceptDraft(BaseModel):
    name: str = Field(description="개념 이름 — 짧은 명사구. 원서면 '부분적분 (Integration by Parts)' 처럼 한국어 + 원어")
    prerequisites: list[str] = Field(description="먼저 알아야 하는 같은 코스 앞쪽 개념의 이름 (없으면 빈 목록)")


class UnitDraft(BaseModel):
    name: str = Field(description="단원(장) 이름 — 출제 범위에 적힌 장 제목 그대로, 원서면 한국어 번역을 앞에")
    concepts: list[ConceptDraft] = Field(description="이 단원에서 시험에 나오는 핵심 개념 3~8개, 배우는 순서대로")


class CourseDraft(BaseModel):
    title: str = Field(description="코스 이름 (사용자가 적은 이름을 다듬어서)")
    category: str = Field(description="분야 이름 — 짧은 한국어 (수학, 회계, 영어, 경제 …)")
    domain: Literal[DOMAINS] = Field(description="분야 키 — 가장 가까운 것, 없으면 general")
    level: str = Field(description="수준 — 고등, 대학, 자격증, 공무원, 어학 중 가장 가까운 것 (또는 짧게 직접)")
    language: Literal["ko", "en"] = Field(description="교재·시험 언어")
    aliases: list[str] = Field(description="사용자가 이 코스를 부를 만한 짧은 이름 3~6개 (공백 없이 소문자, 예: 편입수학, 미적분학)")
    units: list[UnitDraft] = Field(description="출제 범위의 장 순서대로")


COURSE_INSTRUCTIONS = """당신은 여러 시험의 커리큘럼을 설계하는 교육 전문가입니다. 학생이 준 시험·과목·교재·출제 범위로 학습용 개념 트리를 만듭니다.
- 출제 범위에 적힌 장(章)을 순서 그대로 단원으로 만든다. 범위에 없는 장은 추가하지 않는다
- 단원마다 그 시험에서 실제로 묻는 핵심 개념을 3~8개, 배우는 순서대로 적는다. 너무 넓지도(단원 이름 반복) 좁지도(공식 하나) 않게
- 교재의 본문이나 문제를 옮겨 적지 않는다. 그 분야의 일반 지식으로 개념 이름만 붙인다
- 선수 개념은 같은 코스 안에서 앞에 나온 개념 이름만 쓴다
- 이모지는 쓰지 않는다"""


class CourseError(Exception):
    pass


def format_issues(d: CourseDraft) -> list[str]:
    errors = []
    if not 1 <= len(d.units) <= 40:
        errors.append(f"단원 {len(d.units)}개")
    names = [c.name.strip() for u in d.units for c in u.concepts]
    if any(not 1 <= len(u.concepts) <= 15 for u in d.units):
        errors.append("단원별 개념 수가 1~15개를 벗어남")
    if len(names) > 400 or any(not n or len(n) > 120 for n in names) or any(not u.name.strip() for u in d.units):
        errors.append("개념 이름이 비었거나 너무 김")
    if len(set(names)) != len(names):
        errors.append("같은 이름의 개념")
    return errors


def _alias(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())[:60]


def create_course(db: Session, llm: LLM, user: m.User, *, title: str, scope_text: str, exam: str = "", level: str = "",
                  textbook: str = "") -> m.Course:
    s = get_settings()
    prompt = (f"코스 이름: {title}\n시험: {exam or '(적지 않음)'}\n수준: {level or '(적지 않음)'}\n"
              f"교재: {textbook or '(적지 않음)'}\n\n출제 범위:\n{scope_text.strip()}")
    draft, reason = None, "만들지 못함"
    for _ in range(s.ai_max_attempts):
        try:
            res = llm.structured(model=s.openai_model_generate, effort="medium", instructions=COURSE_INSTRUCTIONS,
                                 prompt=prompt, schema=CourseDraft, max_output_tokens=24000)
            u = res.usage
            db.add(m.LLMCall(purpose="course", model=u.model, ok=True, user_id=user.id, cost_usd=u.cost_usd,
                             input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                             reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))
        except LLMError as e:
            db.add(m.LLMCall(purpose="course", model=s.openai_model_generate, ok=False, error=str(e), user_id=user.id))
            reason = f"생성 실패: {e}"
            continue
        if errors := format_issues(res.data):
            reason = f"형식 오류: {', '.join(errors)}"
            continue
        draft = res.data
        break
    if draft is None:
        db.commit()  # 실패해도 호출 기록(비용)은 남긴다
        raise CourseError(reason)

    cid = f"c{uuid.uuid4().hex[:10]}"
    aliases = list(dict.fromkeys(_alias(a) for a in [title, *draft.aliases] if a.strip()))[:8]
    course = m.Course(id=cid, title=(draft.title.strip() or title)[:120], exam=exam[:120], category=draft.category.strip()[:40],
                      domain=draft.domain, level=(level or draft.level).strip()[:40], textbook=textbook[:200],
                      language=draft.language, scope_text=scope_text.strip(), aliases=aliases, source="user",
                      owner_user_id=user.id)
    db.add(course)
    db.flush()
    common = {"domain": draft.domain, "course_id": cid, "curriculum": ""}
    db.add(m.Concept(id=cid, name=course.title, level="subject", **common))
    db.flush()
    ids: dict[str, str] = {}
    for ui, unit in enumerate(draft.units, 1):
        uid = f"{cid}.u{ui}"
        db.add(m.Concept(id=uid, name=unit.name.strip()[:120], level="unit", parent_id=cid, position=ui - 1, **common))
        db.flush()
        for ci, c in enumerate(unit.concepts, 1):
            name = c.name.strip()[:120]
            pre = [ids[p.strip()] for p in c.prerequisites if p.strip() in ids]
            ids[name] = f"{uid}.c{ci}"
            db.add(m.Concept(id=ids[name], name=name, level="concept", parent_id=uid, position=ci - 1, prerequisites=pre, **common))
    db.commit()
    return course


# ---------- 목록 ----------
def list_courses(db: Session, user: m.User) -> list[CourseOut]:
    """모든 코스 (공식 템플릿 먼저, 그다음 사용자 코스 최신순) + 단원·개념 수."""
    counts = dict(((cid, lvl), n) for cid, lvl, n in db.execute(
        select(m.Concept.course_id, m.Concept.level, func.count()).group_by(m.Concept.course_id, m.Concept.level)))
    q = select(m.Course).order_by(m.Course.source.desc(), m.Course.created_at.desc(), m.Course.id)  # template > user
    return [CourseOut.model_validate(c).model_copy(update={
        "units": counts.get((c.id, "unit"), 0), "concepts": counts.get((c.id, "concept"), 0),
        "mine": c.owner_user_id == user.id}) for c in db.scalars(q)]


def my_concepts(db: Session, user: m.User) -> list[m.Concept]:
    """화면이 처음 받을 개념 — 공식 템플릿 + 내 프로젝트의 코스 + 내가 만든 코스. (다른 코스는 열 때 받는다)"""
    used = select(m.Project.subject_id).where(m.Project.user_id == user.id)
    mine = select(m.Course.id).where((m.Course.source == "template") | (m.Course.owner_user_id == user.id) | m.Course.id.in_(used))
    q = (select(m.Concept).where(m.Concept.course_id.in_(mine))
         .order_by(m.Concept.course_id, m.Concept.level != "subject", m.Concept.position, m.Concept.id))
    return list(db.scalars(q))


def course_concepts(db: Session, course_id: str) -> list[m.Concept]:
    q = select(m.Concept).where(m.Concept.course_id == course_id).order_by(m.Concept.level != "subject", m.Concept.position, m.Concept.id)
    return list(db.scalars(q))
