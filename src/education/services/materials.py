"""기출·시험지 업로드와 AI 분석.

업로드한 PDF·사진을 AI 가 읽어 문제마다 본문·보기·정답·개념·난이도를 뽑아 problems 에 PAST_EXAM 으로 저장한다.
기출 원문은 저작권이 있으므로 올린 사람에게만 보이게(owner_user_id) 저장하고, 새 문제를 만들 때 본보기로 쓴다.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from education.config import ROOT, get_settings
from education.db import models as m
from education.schemas import ProblemSource, ProblemType, VerificationStatus
from education.services.llm import LLM, Attachment, LLMError, get_llm

log = logging.getLogger(__name__)

UPLOAD_DIR = ROOT / "data" / "uploads"
ALLOWED_TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 30


class ExtractedProblem(BaseModel):
    number: int | None = Field(description="시험지에 적힌 문항 번호, 없으면 null")
    stem: str = Field(description="문제 본문 (수식은 LaTeX 를 $ 로 감쌈)")
    choices: list[str] = Field(description="보기 내용 (번호 없이). 단답형·서술형이면 빈 목록")
    answer: str | None = Field(description="시험지·정답표에 정답이 있으면 — 객관식은 보기 번호 1~5, 단답형은 값. 없으면 null (추측 금지)")
    concept_id: str = Field(description="주어진 개념 목록 중 가장 알맞은 id, 없으면 빈 문자열")
    difficulty: int = Field(description="수능 기준 난이도 1(2점 기본)~5(4점 킬러) 추정")
    needs_figure: bool = Field(description="그림·그래프·표가 있어야 풀 수 있으면 true")


class Extraction(BaseModel):
    problems: list[ExtractedProblem]


EXTRACT_INSTRUCTIONS = r"""당신은 시험지를 디지털 문제 은행으로 옮기는 편집자입니다.
첨부한 시험지(PDF 또는 사진)의 모든 문항을 빠짐없이 순서대로 옮깁니다.
- 본문과 보기는 원문 그대로 옮기고, 수식은 LaTeX 로 쓰고 $ 로 감싼다 ($\dfrac{1}{2}$, $\displaystyle\int_0^1 f(x)\,dx$, $\mathrm{H_2O}$)
- 보기 번호(①, (1) 등)는 빼고 내용만 choices 에 넣는다
- 정답은 시험지나 정답표에 실제로 적혀 있을 때만 옮기고, 없으면 null. 직접 풀어서 채우지 않는다
- 그림·그래프·표가 있어야 풀 수 있는 문항은 needs_figure 를 true 로 하고, 그림의 핵심 정보를 글로 짧게 설명해 본문 끝에 [그림: …] 으로 덧붙인다
- concept_id 는 주어진 목록에서만 고른다"""


def delete_user_files(user_id: uuid.UUID) -> None:
    """회원 탈퇴 — 그 사용자가 올린 기출 파일을 모두 지운다."""
    shutil.rmtree(UPLOAD_DIR / str(user_id), ignore_errors=True)


def validate_upload(content_type: str, data: bytes) -> str | None:
    """문제가 있으면 사용자에게 보여 줄 오류 문장."""
    if content_type not in ALLOWED_TYPES:
        return "PDF 또는 사진(PNG·JPG·WEBP)만 올릴 수 있어요"
    if len(data) > MAX_BYTES:
        return "파일은 20MB 까지 올릴 수 있어요"
    if content_type == "application/pdf":
        try:
            pages = len(PdfReader(BytesIO(data)).pages)
        except Exception:
            return "PDF 를 열 수 없어요. 파일이 손상되었는지 확인해 주세요"
        if pages > MAX_PDF_PAGES:
            return f"PDF 는 {MAX_PDF_PAGES}쪽까지 올릴 수 있어요 (지금 {pages}쪽)"
    return None


def save_upload(user: m.User, project: m.Project, filename: str, content_type: str, data: bytes,
                rights_confirmed: bool) -> m.Material:
    material_id = uuid.uuid4()
    folder = UPLOAD_DIR / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{material_id}{ALLOWED_TYPES[content_type]}"
    path.write_bytes(data)
    return m.Material(id=material_id, user_id=user.id, project_id=project.id, filename=Path(filename).name[:255],
                      content_type=content_type, size_bytes=len(data), storage_path=str(path.relative_to(UPLOAD_DIR)),
                      rights_confirmed=rights_confirmed)


def scope_concepts(db: Session, project: m.Project) -> list[m.Concept]:
    scope = project.unit_ids or [project.subject_id]
    rows = db.scalars(select(m.Concept).where(m.Concept.level == "concept").order_by(m.Concept.id))
    return [c for c in rows if any(c.id.startswith(f"{s}.") for s in scope)]


def _to_problem(db: Session, ex: ExtractedProblem, material: m.Material, project: m.Project,
                concept_ids: set[str]) -> m.Problem:
    mc = len(ex.choices) == 5
    answer = (ex.answer or "").strip()
    if mc and answer not in {"1", "2", "3", "4", "5"}:
        answer = ""  # 정답을 보기 번호로 못 옮기면 정답 없음으로 둔다
    concept = db.get(m.Concept, ex.concept_id) if ex.concept_id in concept_ids else None
    domain = concept.domain if concept else db.get(m.Concept, project.subject_id).domain
    # 정답이 있고 그림 없이 풀 수 있는 문항만 학생에게 낼 수 있다. 나머지는 본보기로만 쓴다
    servable = bool(answer) and not ex.needs_figure
    p = m.Problem(
        id=f"px_{uuid.uuid4().hex[:12]}", domain=domain, difficulty=min(5, max(1, ex.difficulty)),
        problem_type=ProblemType.MULTIPLE_CHOICE if mc else ProblemType.SHORT_ANSWER,
        stem=ex.stem, choices=ex.choices if mc else None, answer=answer,
        solution="기출 문제 — 해설은 AI 연결 후 생성돼요", source=ProblemSource.PAST_EXAM,
        verification=VerificationStatus.VERIFIED if servable else VerificationStatus.PENDING,
        owner_user_id=material.user_id, material_id=material.id,
        generation_meta={"number": ex.number, "needs_figure": ex.needs_figure, "has_answer": bool(answer)},
    )
    db.add(p)
    db.flush()
    if concept:
        db.add(m.ProblemConcept(problem_id=p.id, concept_id=concept.id))
    return p


def process(material_id: uuid.UUID, open_session: Callable[[], AbstractContextManager[Session]],
            llm: LLM | None = None) -> None:
    """업로드 직후 백그라운드에서 실행: 시험지 → 문제 목록."""
    llm = llm or get_llm()
    s = get_settings()
    with open_session() as db:
        material = db.get(m.Material, material_id)
        if material is None:
            return
        if llm is None:
            material.status, material.error = "failed", "AI 가 설정되지 않아 분석할 수 없어요"
            db.commit()
            return
        material.status = "extracting"
        db.commit()

        project = db.get(m.Project, material.project_id)
        concepts = scope_concepts(db, project)
        concept_list = "\n".join(f"{c.id}: {c.name}" for c in concepts)
        data = (UPLOAD_DIR / material.storage_path).read_bytes()
        try:
            result = llm.structured(
                model=s.openai_model_generate, effort="medium", instructions=EXTRACT_INSTRUCTIONS,
                prompt=f"과목: {db.get(m.Concept, project.subject_id).name}\n개념 목록:\n{concept_list}",
                schema=Extraction, max_output_tokens=32000,
                files=[Attachment(data=data, mime=material.content_type, filename=material.filename)],
            )
        except LLMError as e:
            log.warning("기출 분석 실패 %s: %s", material_id, e)
            db.add(m.LLMCall(purpose="extract", model=s.openai_model_generate, ok=False, error=str(e), user_id=material.user_id))
            material.status, material.error = "failed", "시험지를 읽지 못했어요. 더 선명한 파일로 다시 올려 주세요"
            db.commit()
            return

        ids = {c.id for c in concepts}
        problems = [_to_problem(db, ex, material, project, ids) for ex in result.data.problems if ex.stem.strip()]
        u = result.usage
        db.add(m.LLMCall(purpose="extract", model=u.model, ok=True, user_id=material.user_id, cost_usd=u.cost_usd,
                         input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                         reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))
        material.problem_count = len(problems)
        material.status = "ready" if problems else "failed"
        material.error = None if problems else "시험지에서 문제를 찾지 못했어요"
        db.commit()
