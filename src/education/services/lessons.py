"""개념 레슨 — 글 대신 그림·단계·공식 카드·예제·확인 퀴즈로 배우는 개념 페이지 (라이브러리).

- 레슨은 개념마다 한 번 만들어 모든 사용자가 같이 쓴다 (concept_lessons). 사람마다 다른 부분(내 오답·팁)은
  기존 '내 맞춤 개념 정리'(services/notes.py)가 맡는다
- 생성 에이전트가 레슨을 쓰고, 검증 에이전트가 정의·공식·예제 답·퀴즈 정답·그림 내용을 따로 확인한다. 통과한 것만 저장
- 시각 블록은 AI 가 '데이터'만 낸다. 함수 그래프의 점은 서버가 SymPy 로 계산하고(explain._graph_payload),
  나머지(표·흐름도·관계도·수직선·막대·연표)는 화면이 SVG/HTML 로 그린다 — AI 가 찍은 좌표를 믿지 않는다
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.services.explain import Graph, _graph_payload
from education.services.generator import CallLog, _concept_brief
from education.services.llm import LLM, LLMError

log = logging.getLogger(__name__)


# ---------- 시각 블록 ----------
class TableBlock(BaseModel):
    headers: list[str] = Field(description="열 이름 2~4개")
    rows: list[list[str]] = Field(description="행 2~8개, 각 행은 열 수와 같은 칸. 칸 안 수식은 $...$")


class FlowItem(BaseModel):
    label: str = Field(description="단계 이름 (짧게)")
    detail: str = Field(description="이 단계에서 일어나는 일 한 문장. 수식은 $...$")


class TreeItem(BaseModel):
    id: str = Field(description="노드 id (영문·숫자, 예: n1)")
    parent: str = Field(description="부모 노드 id. 맨 위 노드는 빈 문자열")
    label: str
    detail: str = Field(description="짧은 설명. 없으면 빈 문자열")


class LinePoint(BaseModel):
    x: float
    label: str
    closed: bool = Field(description="점을 포함하면 true (색칠한 점), 포함하지 않으면 false (빈 점)")


class LineRange(BaseModel):
    start: float
    end: float
    label: str
    to_left: bool = Field(description="왼쪽으로 끝없이 이어지면 true (start 는 무시)")
    to_right: bool = Field(description="오른쪽으로 끝없이 이어지면 true (end 는 무시)")


class NumberLine(BaseModel):
    min: float
    max: float
    points: list[LinePoint]
    ranges: list[LineRange]


class Bar(BaseModel):
    label: str
    value: float


class Bars(BaseModel):
    unit: str = Field(description="값의 단위 (예: %, 명, g). 없으면 빈 문자열")
    items: list[Bar] = Field(description="막대 2~8개")


class TimeItem(BaseModel):
    when: str = Field(description="시기 (예: 1592년, 1단계)")
    label: str
    detail: str = Field(description="한 문장. 없으면 빈 문자열")


class Visual(BaseModel):
    kind: Literal["graph", "table", "flow", "tree", "numberline", "bars", "timeline"]
    title: str = Field(description="그림 제목")
    caption: str = Field(description="그림에서 무엇을 보면 되는지 한 문장. 수식은 $...$")
    graph: Graph | None = Field(description="kind 가 graph 일 때만. 아니면 null")
    table: TableBlock | None = Field(description="kind 가 table 일 때만. 아니면 null")
    flow: list[FlowItem] | None = Field(description="kind 가 flow 일 때만 (3~7단계). 아니면 null")
    tree: list[TreeItem] | None = Field(description="kind 가 tree 일 때만 (노드 3~12개, 맨 위 하나). 아니면 null")
    numberline: NumberLine | None = Field(description="kind 가 numberline 일 때만. 아니면 null")
    bars: Bars | None = Field(description="kind 가 bars 일 때만. 아니면 null")
    timeline: list[TimeItem] | None = Field(description="kind 가 timeline 일 때만 (3~8개). 아니면 null")


# ---------- 레슨 ----------
class LessonStep(BaseModel):
    title: str
    text: str = Field(description="해요체 2~4문장. 인라인 수식은 $...$")
    math: str = Field(description="이 단계의 핵심 식 (LaTeX, $ 없이). 없으면 빈 문자열")


class Symbol(BaseModel):
    symbol: str = Field(description="기호 (LaTeX, $ 없이), 예: a")
    meaning: str = Field(description="기호의 뜻, 예: 밑 (1이 아닌 양수)")


class Formula(BaseModel):
    name: str
    latex: str = Field(description="공식 (LaTeX, $ 없이)")
    symbols: list[Symbol] = Field(description="공식에 나오는 기호와 뜻 1~5개")
    when: str = Field(description="언제 쓰는지 한 문장")


class Example(BaseModel):
    question: str = Field(description="이 개념을 바로 쓰는 짧은 예제. 수식은 $...$")
    steps: list[LessonStep] = Field(description="풀이 단계 2~5개")
    answer: str = Field(description="최종 답 (짧게, 수식은 $...$)")


class QuizItem(BaseModel):
    question: str = Field(description="개념을 이해했는지 확인하는 짧은 문제. 수식은 $...$")
    choices: list[str] = Field(description="보기 정확히 4개")
    answer: int = Field(description="정답 보기 번호 1~4")
    why: str = Field(description="정답인 이유 한두 문장")


class LessonContent(BaseModel):
    hook: str = Field(description="한 줄 직관 — 이 개념을 한 문장으로 쉽게 (예: 로그는 '몇 번 곱해야 하나?'를 묻는 질문이에요)")
    visuals: list[Visual] = Field(description="이해를 돕는 그림 1~3개")
    basics: list[LessonStep] = Field(description="기본 이해 — 처음 배우는 학생이 따라오도록 3~6단계")
    deep: list[LessonStep] = Field(description="심화 — 왜 그렇게 되는지(원리·증명·유도) 2~4단계")
    exam: list[LessonStep] = Field(description="시험 적용 — 자주 나오는 출제 유형과 접근법 2~4개")
    formulas: list[Formula] = Field(description="꼭 알아야 할 공식·정의 0~4개 (공식이 없는 개념이면 빈 목록)")
    example: Example
    pitfalls: list[str] = Field(description="자주 틀리는 점 2~4개")
    quiz: list[QuizItem] = Field(description="확인 퀴즈 정확히 3문제")


class LessonVerdict(BaseModel):
    accurate: bool = Field(description="정의·공식·설명·그림 내용에 틀린 것이 없고 코스 범위·수준 안이면 true")
    issues: list[str] = Field(description="발견한 오류 (틀린 공식·설명, 사실과 다른 표·흐름·연표, 엉뚱한 그래프 식 등)")
    example_answer: str = Field(description="예제를 스스로 풀어 구한 최종 답")
    example_correct: bool = Field(description="스스로 구한 답이 출제자의 답과 같으면 true")
    quiz_issues: list[str] = Field(description="정답 번호가 틀렸거나 정답이 둘 이상인 퀴즈 (문제를 함께 적기)")


INSTRUCTIONS = r"""당신은 시험 대비 학원의 베테랑 강사이자 교재 디자이너입니다. 개념 하나를 '읽는 글'이 아니라 '보고 따라오는 레슨'으로 만듭니다.
- 주어진 코스(시험·수준·교육과정·교재) 범위 안에서 정확하게, 그 수준의 용어로 쓴다. 코스 언어가 영어면 핵심 용어에 영어를 함께 적는다
- hook 은 비유나 질문으로 개념의 핵심을 한 문장에 담는다
- visuals 는 개념에 가장 잘 맞는 그림을 1~3개 고른다
  · graph: 함수·그래프 모양이 핵심일 때 (수학·물리). 곡선 식은 x 의 식으로, 숫자·x·+ - * / ^ ( )·sin cos tan asin acos atan sinh cosh tanh exp log sqrt abs pi e 만 쓴다. 곱셈은 *, 함수 인자는 괄호
  · table: 둘 이상을 비교하거나 경우를 나눌 때
  · flow: 순서가 있는 과정·절차·알고리즘
  · tree: 분류·계층·포함 관계
  · numberline: 부등식·구간·범위
  · bars: 양을 비교할 때 (값은 개념을 설명하는 데 쓰는 예시 값임을 caption 에 밝힌다. 실제 통계를 지어내지 않는다)
  · timeline: 시대·사건 순서
  kind 에 맞는 칸 하나만 채우고 나머지는 null 로 둔다
- basics → deep → exam 은 같은 내용을 되풀이하지 않고 점점 깊어지게 쓴다
- 예제는 끝까지 계산해 검산하고, 퀴즈는 정답이 하나뿐이게 만든다. 보기는 그럴듯한 오답을 섞는다
- 수식은 LaTeX 로 쓰고 글 안에서는 $ 로 감싼다. 화학식은 $\mathrm{H_2O}$ 처럼 쓴다
- 한국어 해요체로, 학생에게 직접 말하듯 쉽게 쓴다. 이모지는 쓰지 않는다"""

VERIFIER_INSTRUCTIONS = """당신은 교재 감수위원입니다. 강사가 만든 개념 레슨을 검토합니다.
- 모든 정의·공식·설명, 그리고 그림(표 칸, 흐름 순서, 분류, 수직선 구간, 그래프 식, 연표)의 내용이 사실과 맞는지 스스로 확인한다
- 예제는 풀이를 보지 말고 문제만 보고 처음부터 풀어 example_answer 에 쓴 뒤 출제자의 답과 비교한다
- 퀴즈마다 정답 번호가 맞는지, 정답이 하나뿐인지 확인한다
- 틀리거나 오해를 부르는 내용, 코스 범위·수준 밖의 내용이 있으면 accurate 를 false 로 하고 issues 에 구체적으로 쓴다"""


class LessonError(Exception):
    """개념이 아니거나, 검증을 끝내 통과하지 못함."""


def _visual_payload(v: Visual) -> dict | None:
    """화면에 보낼 그림 — 종류에 맞는 칸만, 그래프는 서버가 점을 계산. 쓸 수 없으면 None"""
    base = {"kind": v.kind, "title": v.title[:80], "caption": v.caption[:200]}
    if v.kind == "graph":
        g = _graph_payload(v.graph) if v.graph else None
        return {**base, "graph": g} if g else None
    if v.kind == "table" and v.table and len(v.table.headers) >= 2:
        n = len(v.table.headers)
        rows = [(r + [""] * n)[:n] for r in v.table.rows[:10] if any(c.strip() for c in r)]
        return {**base, "table": {"headers": v.table.headers[:5], "rows": rows}} if rows else None
    if v.kind == "flow" and v.flow and len(v.flow) >= 2:
        return {**base, "flow": [x.model_dump() for x in v.flow[:8]]}
    if v.kind == "tree" and v.tree and len(v.tree) >= 2:
        ids = {t.id for t in v.tree}
        nodes = [{**t.model_dump(), "parent": t.parent if t.parent in ids and t.parent != t.id else ""} for t in v.tree[:14]]
        return {**base, "tree": nodes} if sum(1 for t in nodes if not t["parent"]) >= 1 else None
    if v.kind == "numberline" and v.numberline and v.numberline.max > v.numberline.min:
        return {**base, "numberline": v.numberline.model_dump()}
    if v.kind == "bars" and v.bars and len(v.bars.items) >= 2:
        return {**base, "bars": {"unit": v.bars.unit, "items": [b.model_dump() for b in v.bars.items[:10]]}}
    if v.kind == "timeline" and v.timeline and len(v.timeline) >= 2:
        return {**base, "timeline": [t.model_dump() for t in v.timeline[:10]]}
    return None


def format_issues(d: LessonContent) -> list[str]:
    errors = []
    if not d.hook.strip() or not 2 <= len(d.basics) <= 7:
        errors.append("한 줄 직관 또는 기본 이해 단계 수")
    if not d.visuals:
        errors.append("그림 없음")
    if len(d.quiz) != 3 or any(len(q.choices) != 4 or not 1 <= q.answer <= 4 for q in d.quiz):
        errors.append("퀴즈는 3문제, 보기 4개, 정답 1~4")
    if not d.example.question.strip() or not d.example.steps:
        errors.append("예제")
    return errors


def _review_text(d: LessonContent) -> str:
    steps = lambda xs: "\n".join(f"- {s.title}: {s.text} {s.math}" for s in xs)  # noqa: E731
    vis = "\n".join(f"- [{v.kind}] {v.title}: {v.model_dump_json(include={'graph', 'table', 'flow', 'tree', 'numberline', 'bars', 'timeline'}, exclude_none=True)}"
                    for v in d.visuals)
    formulas = "\n".join(f"- {f.name}: {f.latex} ({', '.join(f'{s.symbol}={s.meaning}' for s in f.symbols)})" for f in d.formulas)
    quiz = "\n".join(f"{i}. {q.question} / 보기: {' | '.join(q.choices)} / 정답 {q.answer}" for i, q in enumerate(d.quiz, 1))
    return (f"[한 줄 직관]\n{d.hook}\n\n[그림]\n{vis}\n\n[기본]\n{steps(d.basics)}\n\n[심화]\n{steps(d.deep)}\n\n[시험 적용]\n{steps(d.exam)}"
            f"\n\n[공식]\n{formulas}\n\n[예제]\n{d.example.question}\n\n[출제자의 예제 풀이]\n{steps(d.example.steps)}\n답: {d.example.answer}"
            f"\n\n[자주 틀리는 점]\n" + "\n".join(f"- {x}" for x in d.pitfalls) + f"\n\n[확인 퀴즈]\n{quiz}")


def to_payload(d: LessonContent) -> dict:
    out = d.model_dump(exclude={"visuals"})
    out["visuals"] = [p for v in d.visuals[:3] if (p := _visual_payload(v))]
    return out


def get_lesson(db: Session, concept_id: str) -> m.ConceptLesson | None:
    return db.get(m.ConceptLesson, concept_id)


def create_lesson(db: Session, llm: LLM, user: m.User, concept_id: str) -> m.ConceptLesson:
    """레슨을 만들고 검증한다. 이미 있으면 그대로 돌려준다 (모두가 같이 쓰는 레슨)"""
    concept = db.get(m.Concept, concept_id)
    if concept is None or concept.level != "concept":
        raise LessonError("레슨은 단원이 아니라 개념에서 만들 수 있어요")
    if existing := get_lesson(db, concept_id):
        return existing
    s = get_settings()
    brief = _concept_brief(db, concept_id)
    calls: list[CallLog] = []
    draft = verdict = None
    reason = "생성하지 못함"
    prompt = brief
    for _ in range(s.ai_max_attempts):
        try:
            gen = llm.structured(model=s.openai_model_generate, effort=s.openai_effort_generate, instructions=INSTRUCTIONS,
                                 prompt=prompt, schema=LessonContent, max_output_tokens=16000)
            calls.append(CallLog("lesson_generate", gen.usage, s.openai_model_generate))
        except LLMError as e:
            calls.append(CallLog("lesson_generate", None, s.openai_model_generate, str(e)))
            reason = f"생성 실패: {e}"
            continue
        draft = gen.data
        if errors := format_issues(draft):
            reason = f"형식 오류: {', '.join(errors)}"
            continue
        try:
            ver = llm.structured(model=s.openai_model_verify, effort=s.openai_effort_verify, instructions=VERIFIER_INSTRUCTIONS,
                                 prompt=f"{brief}\n\n{_review_text(draft)}", schema=LessonVerdict)
            calls.append(CallLog("lesson_verify", ver.usage, s.openai_model_verify))
        except LLMError as e:
            calls.append(CallLog("lesson_verify", None, s.openai_model_verify, str(e)))
            reason = f"검증 실패: {e}"
            continue
        verdict = ver.data
        if not verdict.accurate or verdict.issues:
            reason = f"내용 오류: {'; '.join(verdict.issues) or '검증자가 오류 지적'}"
        elif not verdict.example_correct:
            reason = f"예제 답 불일치: 검증 {verdict.example_answer}"
        elif verdict.quiz_issues:
            reason = f"퀴즈 오류: {'; '.join(verdict.quiz_issues)}"
        else:
            reason = None
            break
        prompt = f"{brief}\n\n앞선 레슨을 감수위원이 돌려보냈어요: {reason}\n이 점을 고쳐 처음부터 다시 만들어 주세요."

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
        raise LessonError(reason)

    content = to_payload(draft)
    meta = {"generate_model": s.openai_model_generate, "verify_model": s.openai_model_verify,
            "verifier_example_answer": verdict.example_answer, "by": str(user.id)}
    db.execute(insert(m.ConceptLesson).values(concept_id=concept_id, content=content, generation_meta=meta)
               .on_conflict_do_nothing(index_elements=["concept_id"]))  # 동시에 만든 사람이 있으면 먼저 저장된 것을 쓴다
    db.commit()
    return get_lesson(db, concept_id)
