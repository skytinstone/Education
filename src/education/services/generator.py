"""AI 문제 생성 + 검증 엔진.

생성 에이전트가 문제·정답·해설을 만들면, 검증 에이전트가 정답을 모르는 상태에서 독립적으로 다시 푼다.
형식 검사를 통과하고, 검증자가 같은 답을 고르고, 문제 자체에 결함(복수 정답·조건 누락 등)이 없을 때만
VERIFIED 로 저장해 학생에게 낸다. 실패한 문제도 REJECTED 로 남겨 품질 분석에 쓴다.

(계산을 코드로 다시 확인하는 단계는 AI 가 만든 코드를 안전하게 실행할 격리 환경을 갖춘 뒤에 붙인다.)
"""

from __future__ import annotations

import random
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.schemas import ProblemSource, ProblemType, VerificationStatus
from education.services import learning
from education.services.llm import LLM, LLMError, Usage

DIFFICULTY_GUIDE = {
    1: "2점 수준 — 개념·공식을 바로 적용하는 기본 문제",
    2: "쉬운 3점 수준 — 한두 단계 계산",
    3: "3점 수준 — 개념 두 개를 연결하거나 여러 단계 계산",
    4: "4점 수준 — 조건 해석과 여러 개념의 결합, 흔한 실수를 노리는 함정 포함",
    5: "4점 고난도(킬러) — 조건을 깊게 해석해야 하고 풀이 방향을 스스로 찾아야 함",
}


# ---------- 에이전트 입출력 ----------
class GeneratedProblem(BaseModel):
    stem: str = Field(description="문제 본문")
    choices: list[str] = Field(description="보기 정확히 5개 (번호 없이 내용만)")
    answer: Literal["1", "2", "3", "4", "5"] = Field(description="정답 보기 번호")
    solution: str = Field(description="학생이 따라갈 수 있는 단계별 해설")
    traps: list[str] = Field(description="이 문제가 노리는 흔한 실수나 함정")


class GeneratedShort(BaseModel):
    stem: str = Field(description="문제 본문")
    answer: int = Field(description="정답 — 0 이상 999 이하의 정수 하나")
    solution: str = Field(description="학생이 따라갈 수 있는 단계별 해설")
    traps: list[str] = Field(description="이 문제가 노리는 흔한 실수나 함정")


class Verdict(BaseModel):
    answer: Literal["1", "2", "3", "4", "5", "none"] = Field(description="스스로 풀어서 고른 보기 번호, 정답이 없으면 none")
    work: str = Field(description="풀이 과정 요약")
    well_posed: bool = Field(description="정답이 정확히 하나이고 조건에 모순·누락이 없으면 true")
    issues: list[str] = Field(description="발견한 문제점 (복수 정답, 조건 누락, 계산 오류, 교육과정 범위 밖, 난이도 불일치 등)")


class ShortVerdict(BaseModel):
    answer: int | None = Field(description="스스로 풀어서 구한 답 (정수), 구할 수 없으면 null")
    work: str = Field(description="풀이 과정 요약")
    well_posed: bool = Field(description="답이 정확히 하나로 정해지고 조건에 모순·누락이 없으면 true")
    issues: list[str] = Field(description="발견한 문제점 (답이 여러 개, 조건 누락, 계산 오류, 교육과정 범위 밖 등)")


GENERATOR_INSTRUCTIONS = r"""당신은 한국 대학수학능력시험 출제 경험이 많은 출제위원입니다.
고등학교 2015 개정 교육과정 범위 안에서, 요청한 개념·난이도·문제 형태에 맞는 문제를 하나 만듭니다.

반드시 지킬 것
- 5지선다: 정답은 정확히 하나. 나머지 4개 보기는 그럴듯하지만 분명히 틀려야 하고, 흔한 실수로 나오는 값을 오답으로 넣는다
- 단답형: 수능 단답형처럼 답이 0 이상 999 이하의 정수 하나로 정해지게 만든다
- 참고할 기출 문제가 주어지면 형식·어투·소재의 결을 따르되, 문장과 수치는 그대로 베끼지 말고 새로 만든다
- 모든 수치는 직접 끝까지 계산해서 검산한다. 근삿값이 아닌 정확한 값을 쓴다
- 문제에 필요한 조건은 모두 문제 안에 쓴다 (그림 없이 글만으로 풀 수 있게)
- 수식은 LaTeX 로 쓰고 $ 로 감싼다 (예: $x^2$, $\sqrt{2}$, $\dfrac{1}{2}$, $\log_2 3$). 적분·시그마처럼 크게 보여야 하는 식은 $\displaystyle\int_0^1 f(x)\,dx$ 처럼 쓴다. 단위는 $2\,\mathrm{m/s}$, 화학식은 $\mathrm{H_2O}$ 처럼 쓴다. 보기와 해설도 같은 방식
- 해설은 학생이 혼자 따라갈 수 있게 단계별로, 한국어로 쓴다. 이모지는 쓰지 않는다
- 이미 있는 문제와 소재·수치가 겹치지 않게 새로 만든다"""

VERIFIER_INSTRUCTIONS = """당신은 수능 문제 검토위원입니다. 출제자가 만든 문제를 정답을 모르는 상태에서 직접 풉니다.
- 처음부터 끝까지 스스로 계산해서 답을 구한다. 5지선다는 보기 번호를 고르고(정답이 없으면 none), 단답형은 정수로 답한다
- 정답이 둘 이상이거나, 조건이 모순되거나 빠졌거나, 문제 문장이 모호하거나, 고등학교 교육과정을 벗어나면 well_posed 를 false 로 하고 issues 에 구체적으로 쓴다
- 사소한 표현 개선 의견은 issues 에 넣지 않는다 (정답 판정에 영향을 주는 것만)"""


# ---------- 요청 분석 ----------
@dataclass
class Plan:
    concept_id: str
    difficulty: int
    count: int


# 요청 문장에 나오는 과목 이름 (화면 prototype/app.js 의 SUBJECT_ALIASES 와 같음). II 를 I 보다 먼저 본다
SUBJECT_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("math.math2", ("수학ii", "수학2", "수2")), ("math.math1", ("수학i", "수학1", "수1")),
    ("math.prob_stat", ("확률과통계", "확통", "확률", "통계")), ("math.calculus", ("미적분", "미적")), ("math.geometry", ("기하",)),
    ("physics.physics1", ("물리학", "물리", "물1")), ("chemistry.chemistry1", ("화학", "화1")),
    ("biology.biology1", ("생명과학", "생명", "생물", "생1", "생과")), ("earth_science.earth1", ("지구과학", "지구", "지학", "지1")),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.lower().replace("Ⅱ", "ii").replace("Ⅰ", "i"))


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[\s·,()과와의]+", name) if len(w) >= 2]


def detect_subject(text: str) -> str | None:
    t = _norm(text)
    # 숫자로 끝나는 별칭은 뒤에 숫자·등급·점·문제가 붙으면 아님 ("수학 10문제", "수학 2등급" 은 수학I·II 가 아니다)
    # (띄어쓰기를 지우면 "물1 3문제" 가 "물13" 이 되므로 이 경우는 띄어쓰기를 남긴 글에서 본다)
    spaced = re.sub(r"\s+", " ", text.lower().replace("Ⅱ", "ii").replace("Ⅰ", "i"))

    def found(k: str) -> bool:
        if not k[-1].isdigit():
            return k in t
        return bool(re.search(r"\s*".join(map(re.escape, k)) + r"(?!\d|등급|점|문제|문항|개)", spaced))
    return next((sid for sid, keys in SUBJECT_ALIASES if any(found(k) for k in keys)), None)


def _in_scope(concept_id: str, scope_ids: list[str]) -> bool:
    return any(concept_id == s or concept_id.startswith(f"{s}.") for s in scope_ids)


def resolve_scope(db: Session, text: str, scope_ids: list[str] | None = None) -> list[str] | None:
    """요청이 가리키는 개념 트리 범위 — 문장의 과목 이름이 프로젝트 범위보다 우선하고, 단원 이름이 있으면 그 단원으로 좁힌다."""
    subject = detect_subject(text)
    base = [subject] if subject else scope_ids
    units = db.scalars(select(m.Concept).where(m.Concept.level == "unit")).all()
    named = [u.id for u in units if (not base or _in_scope(u.id, base)) and any(w in text for w in _words(u.name))]
    return named or base


def plan_request(db: Session, text: str, *, user: m.User | None = None, domain=None, scope_ids: list[str] | None = None,
                 max_count: int = 3) -> Plan | None:
    """요청 문장에서 개념·난이도·문항 수를 읽는다.
    개념 이름의 낱말이 가장 많이 겹치는 개념을 고르고, 개념 이름은 없지만 과목·단원(또는 프로젝트 범위)이 정해지면
    그 안에서 내가 가장 약한 개념(기록이 없으면 아무 개념)을 고른다."""
    subject = detect_subject(text)
    q = select(m.Concept).where(m.Concept.level == "concept")
    if domain and not subject:
        q = q.where(m.Concept.domain == domain)
    all_concepts = list(db.scalars(q))
    base = [subject] if subject else scope_ids
    concepts = [c for c in all_concepts if _in_scope(c.id, base)] if base else all_concepts
    if not concepts:
        return None

    def score(c: m.Concept) -> int:
        return sum(len(w) for w in _words(c.name) if w in text)

    best = max(concepts, key=score)
    if score(best) == 0:
        # 개념 이름은 없다. 범위가 전혀 없거나, 프로젝트 범위 밖의 개념을 콕 집어 말했으면(물리 프로젝트에서 '치환적분') 고르지 않는다
        if not base or (not subject and any(score(c) for c in all_concepts)):
            return None
        scope = resolve_scope(db, text, scope_ids)  # 단원 이름이 있으면 그 단원으로 좁힌다
        pool = [c for c in concepts if _in_scope(c.id, scope)] or concepts
        ids = {c.id for c in pool}
        weak = [w.concept_id for w in learning.concept_stats(db, user) if w.concept_id in ids] if user else []
        best = db.get(m.Concept, weak[0]) if weak else random.choice(pool)

    difficulty = 3
    if re.search(r"킬러|최고난도", text):
        difficulty = 5
    elif re.search(r"4\s*점|어려운|고난도", text):
        difficulty = 4
    elif re.search(r"2\s*점|기초|쉬운", text):
        difficulty = 1
    count_match = re.search(r"(\d+)\s*(문제|문항|개)", text)
    count = max(1, min(int(count_match.group(1)) if count_match else 2, max_count))
    return Plan(concept_id=best.id, difficulty=difficulty, count=count)


# ---------- 생성 · 검증 ----------
@dataclass
class CallLog:
    purpose: str
    usage: Usage | None
    model: str
    error: str | None = None


@dataclass
class Candidate:
    problem: GeneratedProblem | None
    verdict: Verdict | None
    reason: str | None  # 통과 못 한 이유. None 이면 통과
    calls: list[CallLog] = field(default_factory=list)


def format_issues(p: GeneratedProblem | GeneratedShort) -> list[str]:
    """모델 호출 없이 잡을 수 있는 형식 오류."""
    if isinstance(p, GeneratedShort):
        errors = [] if 0 <= p.answer <= 999 else [f"단답형 정답 범위 밖: {p.answer}"]
        return errors + (["본문이나 해설이 비어 있음"] if not p.stem.strip() or not p.solution.strip() else [])
    errors = []
    if len(p.choices) != 5:
        errors.append(f"보기가 {len(p.choices)}개")
    norm = [re.sub(r"\s+", "", c).lower() for c in p.choices]
    if len(set(norm)) != len(norm):
        errors.append("중복된 보기")
    if not p.stem.strip() or not p.solution.strip():
        errors.append("본문이나 해설이 비어 있음")
    if any(not c.strip() for c in p.choices):
        errors.append("빈 보기")
    return errors


def _concept_brief(db: Session, concept_id: str) -> str:
    path, node = [], db.get(m.Concept, concept_id)
    target = node
    while node:
        path.insert(0, node.name)
        node = db.get(m.Concept, node.parent_id) if node.parent_id else None
    pre = [db.get(m.Concept, p).name for p in target.prerequisites if db.get(m.Concept, p)]
    return f"개념: {' > '.join(path)}" + (f"\n선수 개념: {', '.join(pre)}" if pre else "")


def _one(llm: LLM, prompt: str, max_attempts: int, question_type: str = "multiple_choice") -> Candidate:
    """문제 하나: 생성 → 형식 검사 → 독립 검증. 실패하면 max_attempts 까지 다시 만든다."""
    s = get_settings()
    mc = question_type == "multiple_choice"
    gen_schema, ver_schema = (GeneratedProblem, Verdict) if mc else (GeneratedShort, ShortVerdict)
    prompt = f"{prompt}\n문제 형태: {'5지선다' if mc else '단답형 (정답은 0 이상 999 이하의 정수)'}"
    calls: list[CallLog] = []
    last = Candidate(None, None, "생성하지 못함", calls)
    for _ in range(max_attempts):
        try:
            gen = llm.structured(model=s.openai_model_generate, effort=s.openai_effort_generate,
                                 instructions=GENERATOR_INSTRUCTIONS, prompt=prompt, schema=gen_schema)
            calls.append(CallLog("generate", gen.usage, s.openai_model_generate))
        except LLMError as e:
            calls.append(CallLog("generate", None, s.openai_model_generate, str(e)))
            last = Candidate(None, None, f"생성 실패: {e}", calls)
            continue
        problem = gen.data
        if errors := format_issues(problem):
            last = Candidate(problem, None, f"형식 오류: {', '.join(errors)}", calls)
            continue

        question = problem.stem + ("\n\n" + "\n".join(f"{i}) {c}" for i, c in enumerate(problem.choices, 1)) if mc else "\n\n(단답형)")
        try:
            ver = llm.structured(model=s.openai_model_verify, effort=s.openai_effort_verify,
                                 instructions=VERIFIER_INSTRUCTIONS, prompt=question, schema=ver_schema)
            calls.append(CallLog("verify", ver.usage, s.openai_model_verify))
        except LLMError as e:
            calls.append(CallLog("verify", None, s.openai_model_verify, str(e)))
            last = Candidate(problem, None, f"검증 실패: {e}", calls)
            continue
        verdict = ver.data
        if not verdict.well_posed:
            last = Candidate(problem, verdict, f"문제 결함: {'; '.join(verdict.issues) or '검증자가 결함 지적'}", calls)
        elif verdict.answer != problem.answer:
            last = Candidate(problem, verdict, f"정답 불일치: 출제 {problem.answer}, 검증 {verdict.answer}", calls)
        else:
            return Candidate(problem, verdict, None, calls)
    return last


@dataclass
class GenerationReport:
    accepted: list[str]  # 통과한 문제 id
    rejected: list[str]  # 기록만 남긴 문제 id
    reasons: list[str]
    cost_usd: float

    @property
    def calls_summary(self) -> str:
        return f"통과 {len(self.accepted)} · 탈락 {len(self.rejected)} · 비용 ${self.cost_usd:.4f}"


def _exemplar_text(p: m.Problem) -> str:
    lines = [p.stem]
    if p.choices:
        lines += [f"{i}) {c}" for i, c in enumerate(p.choices, 1)]
    if p.answer:
        lines.append(f"정답: {p.answer}")
    return "\n".join(lines)


def generate_problems(db: Session, llm: LLM, *, concept_id: str, difficulty: int, count: int,
                      user: m.User | None = None, question_type: str = "multiple_choice",
                      exemplars: list[m.Problem] | None = None, owner: m.User | None = None) -> GenerationReport:
    """question_type: multiple_choice · short_answer · mixed(번갈아).
    exemplars: 본보기로 삼을 기출 문제. owner: 만든 문제를 그 사용자만 보게 할 때 (기출 기반 문제)."""
    concept = db.get(m.Concept, concept_id)
    if concept is None or concept.level != "concept":
        raise ValueError(f"개념이 아님: {concept_id}")
    s = get_settings()
    recent = list(db.scalars(
        select(m.Problem.stem).join(m.ProblemConcept).where(m.ProblemConcept.concept_id == concept_id)
        .order_by(m.Problem.created_at.desc()).limit(5)))
    prompt = (f"{_concept_brief(db, concept_id)}\n난이도: {difficulty} ({DIFFICULTY_GUIDE[difficulty]})\n"
              + ("\n이미 있는 문제 (겹치지 않게):\n" + "\n".join(f"- {r[:120]}" for r in recent) if recent else "")
              + ("\n\n참고할 기출 문제 (이 결을 따르되 베끼지 말 것):\n\n" + "\n\n---\n\n".join(_exemplar_text(e) for e in exemplars[:3])
                 if exemplars else ""))
    types = ["multiple_choice", "short_answer"] if question_type == "mixed" else [question_type]

    # 문제마다 독립적이라 동시에 만든다 (DB 기록은 아래에서 한 스레드로)
    with ThreadPoolExecutor(max_workers=min(count, 4)) as pool:
        candidates = list(pool.map(lambda i: (_one(llm, prompt, s.ai_max_attempts, types[i % len(types)]), types[i % len(types)]), range(count)))

    report = GenerationReport(accepted=[], rejected=[], reasons=[], cost_usd=0.0)
    for cand, qtype in candidates:
        pid = None
        mc = qtype == "multiple_choice"
        if cand.problem is not None and not format_issues(cand.problem):
            pid = f"ai_{uuid.uuid4().hex[:12]}"
            ok = cand.reason is None
            db.add(m.Problem(
                id=pid, domain=concept.domain, difficulty=difficulty,
                problem_type=ProblemType.MULTIPLE_CHOICE if mc else ProblemType.SHORT_ANSWER,
                stem=cand.problem.stem, choices=cand.problem.choices if mc else None, answer=str(cand.problem.answer),
                owner_user_id=owner.id if owner else None,
                solution=cand.problem.solution, traps=cand.problem.traps, source=ProblemSource.GENERATED,
                verification=VerificationStatus.VERIFIED if ok else VerificationStatus.REJECTED,
                generation_meta={
                    "generate_model": s.openai_model_generate, "verify_model": s.openai_model_verify,
                    "verifier_answer": str(cand.verdict.answer) if cand.verdict else None,
                    "exemplar_ids": [e.id for e in exemplars[:3]] if exemplars else [],
                    "verifier_issues": cand.verdict.issues if cand.verdict else [],
                    "verifier_work": cand.verdict.work if cand.verdict else None,
                    "reject_reason": cand.reason,
                },
            ))
            db.flush()
            db.add(m.ProblemConcept(problem_id=pid, concept_id=concept_id))
            (report.accepted if ok else report.rejected).append(pid)
        if cand.reason:
            report.reasons.append(cand.reason)
        for c in cand.calls:
            cost = c.usage.cost_usd if c.usage else None
            report.cost_usd += cost or 0
            db.add(m.LLMCall(
                purpose=c.purpose, model=c.model, ok=c.error is None, error=c.error, user_id=user.id if user else None,
                problem_id=pid, cost_usd=cost,
                **({"input_tokens": c.usage.input_tokens, "cached_tokens": c.usage.cached_tokens,
                    "output_tokens": c.usage.output_tokens, "reasoning_tokens": c.usage.reasoning_tokens,
                    "latency_ms": c.usage.latency_ms} if c.usage else {}),
            ))
    db.commit()
    return report
