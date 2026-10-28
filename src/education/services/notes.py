"""개인 맞춤 개념 정리 + 암기 카드 (Phase 3).

학습자 한 명의 풀이·오답 기록을 바탕으로 생성 에이전트가 개념 정리와 암기 카드를 만들고,
검증 에이전트가 정의·공식·예제 풀이·카드 정답을 독립적으로 확인한다. 통과한 것만 저장해 보여준다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.schemas import ErrorType
from education.services import learning
from education.services.generator import CallLog, _concept_brief
from education.services.llm import LLM, LLMError

ERROR_NAME = {
    ErrorType.CONCEPT_GAP: "개념 자체를 모름", ErrorType.MISAPPLICATION: "개념 적용 실수", ErrorType.CALCULATION: "계산 실수",
    ErrorType.MISREAD: "조건·문제 오독", ErrorType.TRAP: "함정에 걸림", ErrorType.TIME_PRESSURE: "시간 부족",
    ErrorType.UNKNOWN: "이유 미분류",
}


# ---------- 에이전트 입출력 ----------
class MemoItem(BaseModel):
    title: str = Field(description="외울 것의 이름 (예: 로그의 밑 변환 공식)")
    body: str = Field(description="공식·정의·법칙 그 자체와 한 줄 설명")


class WorkedExample(BaseModel):
    question: str = Field(description="이 개념을 바로 쓰는 짧은 예제 문제")
    solution: str = Field(description="단계별 풀이와 최종 답")


class NoteContent(BaseModel):
    summary: str = Field(description="핵심 정리 — 개념의 뜻, 왜 그렇게 되는지, 언제 쓰는지 (3~6문단)")
    must_memorize: list[MemoItem] = Field(description="꼭 외워야 할 공식·정의 2~6개")
    pitfalls: list[str] = Field(description="자주 틀리는 점 — 학습자의 오답 기록이 있으면 그 유형을 먼저")
    example: WorkedExample
    personal_tip: str = Field(description="이 학습자의 기록에 맞춘 공부 방법 한두 문장 (기록이 없으면 처음 배우는 사람 기준)")


class CardDraft(BaseModel):
    front: str = Field(description="카드 앞면 — 질문")
    back: str = Field(description="카드 뒷면 — 짧고 정확한 답")


class NoteDraft(NoteContent):
    cards: list[CardDraft] = Field(description="암기 카드 4~8장")


class NoteVerdict(BaseModel):
    accurate: bool = Field(description="정의·공식·설명에 틀린 내용이 없고 고등학교 교육과정 범위 안이면 true")
    example_answer: str = Field(description="예제를 스스로 풀어서 구한 최종 답")
    example_correct: bool = Field(description="스스로 구한 답이 출제자 풀이의 최종 답과 같으면 true")
    issues: list[str] = Field(description="발견한 오류 (틀린 공식, 잘못된 설명, 교육과정 밖, 예제 오류 등)")
    card_issues: list[str] = Field(description="뒷면 답이 틀렸거나 앞면 질문과 맞지 않는 카드 (앞면을 함께 적기)")


NOTE_INSTRUCTIONS = r"""당신은 한국 수능 대비 학원의 베테랑 강사입니다. 학생 한 명을 위한 개념 정리 노트와 암기 카드를 만듭니다.
- 고등학교 2015 개정 교육과정 범위 안에서 정확하게 쓴다. 교과서에 없는 용어는 쓰지 않는다
- 학습자 기록이 주어지면 그 학생이 틀린 유형·약한 부분을 더 자세히 설명하고, 자주 틀리는 점에 그 학생의 실수를 먼저 적는다
- 학습자 기록이 없으면 처음 배우는 학생 기준으로 쓴다
- 예제는 이 개념을 바로 쓰는 짧은 문제 하나, 풀이는 끝까지 계산해서 검산한다
- 암기 카드는 앞면이 질문, 뒷면이 짧은 정답. 이미 있는 카드와 겹치지 않게 만든다
- 수식은 LaTeX 로 쓰고 $ 로 감싼다 (예: $\log_a b = \dfrac{\log_c b}{\log_c a}$). 화학식은 $\mathrm{H_2O}$ 처럼 쓴다
- 한국어로, 학생에게 직접 말하듯 쉽게 쓴다"""

NOTE_VERIFIER_INSTRUCTIONS = """당신은 수능 교재 감수위원입니다. 강사가 만든 개념 정리와 암기 카드를 검토합니다.
- 모든 정의·공식·법칙을 스스로 확인한다. 틀리거나 오해를 부르는 설명, 고등학교 교육과정 밖의 내용이 있으면 accurate 를 false 로 하고 issues 에 구체적으로 쓴다
- 예제는 풀이를 보지 말고 문제만 보고 처음부터 스스로 풀어 example_answer 에 쓴 뒤, 출제자의 최종 답과 비교한다
- 암기 카드마다 앞면 질문에 대한 뒷면 답이 정확한지 확인하고, 틀린 카드는 card_issues 에 쓴다
- 사소한 표현 개선 의견은 쓰지 않는다 (내용이 틀린 것만)"""


class NoteError(Exception):
    """개념이 아니거나, 검증을 끝내 통과하지 못함."""


# ---------- 학습자 기록 ----------
def learner_context(db: Session, user: m.User, concept_id: str) -> tuple[str, dict]:
    """개인화에 쓸 기록 — 프롬프트용 글과 generation_meta 에 남길 요약."""
    stats = next((s for s in learning.concept_stats(db, user) if s.concept_id == concept_id), None)
    notes = db.execute(
        select(m.WrongNote, m.Problem).join(m.Problem, m.Problem.id == m.WrongNote.problem_id)
        .join(m.ProblemConcept, m.ProblemConcept.problem_id == m.Problem.id)
        .where(m.WrongNote.user_id == user.id, m.ProblemConcept.concept_id == concept_id)
        .order_by(m.WrongNote.created_at.desc()).limit(5)).all()
    projects = [p for p in db.scalars(select(m.Project).where(m.Project.user_id == user.id))
                if concept_id.startswith(f"{p.subject_id}.")]
    cards = list(db.scalars(select(m.Card.front).where(m.Card.user_id == user.id, m.Card.concept_id == concept_id)))

    lines = []
    if stats:
        lines.append(f"이 개념 풀이: {stats.attempts}문제, 정답률 {round(stats.accuracy * 100)}%")
    for note, p in notes:
        state = "다시 풀어 맞힘" if note.resolved_at else "아직 극복 못 함"
        lines.append(f"오답 ({ERROR_NAME[note.error_type]}, {state}): {p.stem[:160]} / 고른 답 {note.answer}, 정답 {p.answer}")
    for p in projects:
        goal = " · ".join(x for x in (p.goal and f"목표 {p.goal}", p.exam_date and f"시험일 {p.exam_date}") if x)
        lines.append(f"학습 프로젝트: {p.name}" + (f" ({goal})" if goal else ""))
    if cards:
        lines.append("이미 있는 암기 카드 (겹치지 않게): " + " / ".join(c[:60] for c in cards[:12]))
    summary = {"attempts": stats.attempts if stats else 0, "accuracy": stats.accuracy if stats else None,
               "wrong_notes": len(notes), "projects": len(projects)}
    return ("\n".join(lines) or "기록 없음 (처음 배우는 학생)"), summary


# ---------- 생성 · 검증 ----------
def format_issues(d: NoteDraft) -> list[str]:
    errors = []
    if not d.summary.strip() or not d.must_memorize or not d.example.question.strip():
        errors.append("핵심 정리·필수 암기·예제 중 비어 있는 것")
    if not 3 <= len(d.cards) <= 10:
        errors.append(f"카드 {len(d.cards)}장")
    fronts = [re.sub(r"\s+", "", c.front) for c in d.cards]
    if len(set(fronts)) != len(fronts) or any(not c.front.strip() or not c.back.strip() for c in d.cards):
        errors.append("중복되거나 빈 카드")
    return errors


def _review_text(d: NoteDraft) -> str:
    memo = "\n".join(f"- {x.title}: {x.body}" for x in d.must_memorize)
    cards = "\n".join(f"{i}. 앞: {c.front}\n   뒤: {c.back}" for i, c in enumerate(d.cards, 1))
    return (f"[핵심 정리]\n{d.summary}\n\n[필수 암기]\n{memo}\n\n[자주 틀리는 점]\n" + "\n".join(f"- {x}" for x in d.pitfalls)
            + f"\n\n[예제]\n{d.example.question}\n\n[출제자의 예제 풀이]\n{d.example.solution}\n\n[암기 카드]\n{cards}")


@dataclass
class NoteResult:
    note: m.ConceptNote
    added_cards: list[m.Card]


def create_note(db: Session, llm: LLM, user: m.User, concept_id: str) -> NoteResult:
    concept = db.get(m.Concept, concept_id)
    if concept is None or concept.level != "concept":
        raise NoteError("개념 정리는 단원이 아니라 개념에서 만들 수 있어요")
    s = get_settings()
    context, ctx_summary = learner_context(db, user, concept_id)
    prompt = f"{_concept_brief(db, concept_id)}\n\n학습자 기록:\n{context}"

    calls: list[CallLog] = []
    draft = verdict = None
    reason = "생성하지 못함"
    for _ in range(s.ai_max_attempts):
        try:
            gen = llm.structured(model=s.openai_model_generate, effort=s.openai_effort_generate,
                                 instructions=NOTE_INSTRUCTIONS, prompt=prompt, schema=NoteDraft)
            calls.append(CallLog("note_generate", gen.usage, s.openai_model_generate))
        except LLMError as e:
            calls.append(CallLog("note_generate", None, s.openai_model_generate, str(e)))
            reason = f"생성 실패: {e}"
            continue
        draft = gen.data
        if errors := format_issues(draft):
            reason = f"형식 오류: {', '.join(errors)}"
            continue
        try:
            ver = llm.structured(model=s.openai_model_verify, effort=s.openai_effort_verify,
                                 instructions=NOTE_VERIFIER_INSTRUCTIONS,
                                 prompt=f"{_concept_brief(db, concept_id)}\n\n{_review_text(draft)}", schema=NoteVerdict)
            calls.append(CallLog("note_verify", ver.usage, s.openai_model_verify))
        except LLMError as e:
            calls.append(CallLog("note_verify", None, s.openai_model_verify, str(e)))
            reason = f"검증 실패: {e}"
            continue
        verdict = ver.data
        if not verdict.accurate or verdict.issues:
            reason = f"내용 오류: {'; '.join(verdict.issues) or '검증자가 오류 지적'}"
        elif not verdict.example_correct:
            reason = f"예제 답 불일치: 검증 {verdict.example_answer}"
        elif verdict.card_issues:
            reason = f"카드 오류: {'; '.join(verdict.card_issues)}"
        else:
            reason = None
            break

    for c in calls:
        db.add(m.LLMCall(
            purpose=c.purpose, model=c.model, ok=c.error is None, error=c.error, user_id=user.id,
            cost_usd=c.usage.cost_usd if c.usage else None,
            **({"input_tokens": c.usage.input_tokens, "cached_tokens": c.usage.cached_tokens,
                "output_tokens": c.usage.output_tokens, "reasoning_tokens": c.usage.reasoning_tokens,
                "latency_ms": c.usage.latency_ms} if c.usage else {}),
        ))
    if reason is not None:
        db.commit()  # 실패해도 호출 기록(비용)은 남긴다
        raise NoteError(reason)

    content = NoteContent.model_validate(draft.model_dump()).model_dump()
    meta = {"generate_model": s.openai_model_generate, "verify_model": s.openai_model_verify,
            "verifier_example_answer": verdict.example_answer, "context": ctx_summary}
    note_id = db.scalar(
        insert(m.ConceptNote).values(user_id=user.id, concept_id=concept_id, content=content, generation_meta=meta)
        .on_conflict_do_update(constraint="uq_concept_note_user_concept",
                               set_={"content": content, "generation_meta": meta, "created_at": func.now()})
        .returning(m.ConceptNote.id))
    existing = {re.sub(r"\s+", "", f) for f in db.scalars(
        select(m.Card.front).where(m.Card.user_id == user.id, m.Card.concept_id == concept_id))}
    added = [m.Card(user_id=user.id, concept_id=concept_id, front=c.front.strip(), back=c.back.strip())
             for c in draft.cards if re.sub(r"\s+", "", c.front) not in existing]
    db.add_all(added)
    db.commit()
    note = db.get(m.ConceptNote, note_id)
    db.refresh(note)
    return NoteResult(note=note, added_cards=added)
