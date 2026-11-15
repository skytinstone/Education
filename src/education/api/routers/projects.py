import logging
from collections import Counter
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import (
    AskIn, GenerateIn, MaterialOut, PastProblemOut, ProjectIn, ProjectOut, ProjectPatch, ProjectSummary, SessionDetail,
)
from education.api.routers.sessions import session_detail
from education.db import models as m
from education.db.session import session_factory
from education.schemas import ConceptLevel
from education.services import answer_key, explain, generator, jobs, learning, materials, quota, tutor
from education.services.llm import LLMError, get_llm

router = APIRouter(prefix="/projects", tags=["프로젝트"])
log = logging.getLogger(__name__)


def _check_scope(db: Session, subject_id: str, unit_ids: list[str]) -> None:
    subject = db.get(m.Concept, subject_id)
    if subject is None or subject.level != ConceptLevel.SUBJECT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "과목을 다시 골라 주세요")
    if unit_ids:
        valid = set(db.scalars(select(m.Concept.id).where(m.Concept.parent_id == subject_id)))
        if not set(unit_ids) <= valid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "학습 범위가 과목과 맞지 않아요")


@router.get("")
def list_projects(user: CurrentUser, db: DB) -> list[ProjectOut]:
    q = select(m.Project).where(m.Project.user_id == user.id).order_by(m.Project.pinned.desc(), m.Project.created_at)
    return [ProjectOut.model_validate(p) for p in db.scalars(q)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectIn, user: CurrentUser, db: DB) -> ProjectOut:
    _check_scope(db, body.subject_id, body.unit_ids)
    p = m.Project(user_id=user.id, **body.model_dump())
    db.add(p)
    db.commit()
    return ProjectOut.model_validate(p)


@router.get("/{project_id}")
def get_project(project_id: UUID, user: CurrentUser, db: DB) -> ProjectSummary:
    p = owned(db, m.Project, project_id, user)
    attempts = db.scalar(select(func.count()).where(m.Attempt.user_id == user.id, m.Attempt.project_id == p.id))
    open_notes = db.scalar(select(func.count()).where(
        m.WrongNote.user_id == user.id, m.WrongNote.project_id == p.id, m.WrongNote.resolved_at.is_(None)))
    return ProjectSummary(
        project=ProjectOut.model_validate(p), attempts=attempts, open_notes=open_notes,
        accuracy=learning.accuracy(db, user, project_id=p.id),
        weak_concepts=learning.concept_stats(db, user, project_id=p.id)[:3],
    )


@router.patch("/{project_id}")
def update_project(project_id: UUID, body: ProjectPatch, user: CurrentUser, db: DB) -> ProjectOut:
    p = owned(db, m.Project, project_id, user)
    changes = body.model_dump(exclude_unset=True)
    if "subject_id" in changes or "unit_ids" in changes:
        _check_scope(db, changes.get("subject_id", p.subject_id), changes.get("unit_ids", p.unit_ids))
    for k, v in changes.items():
        if v is None and k not in ("exam_date", "textbook_isbn"):
            continue  # exam_date·textbook_isbn 만 null 로 지울 수 있다
        setattr(p, k, v)
    db.commit()
    return ProjectOut.model_validate(p)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: UUID, user: CurrentUser, db: DB) -> Response:
    """프로젝트와 그 안의 대화를 지운다. 풀이 기록과 오답노트는 남는다 (project_id 만 비움)."""
    db.delete(owned(db, m.Project, project_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 기출 업로드 ----------
@router.post("/{project_id}/materials", status_code=status.HTTP_201_CREATED)
def upload_material(project_id: UUID, user: CurrentUser, db: DB, background: BackgroundTasks,
                          file: Annotated[UploadFile, File()], rights_confirmed: Annotated[bool, Form()] = False,
                          kind: Annotated[Literal["past_exam", "textbook", "answer_sheet"], Form()] = "past_exam",
                          answer_for: Annotated[UUID | None, Form()] = None,
                          open_session=Depends(session_factory)) -> MaterialOut:
    """기출·시험지 또는 교재 페이지(PDF·사진)를 올리면 백그라운드에서 AI 가 문제를 뽑는다. 상태는 GET 으로 확인.
    정답 파일(kind=answer_sheet)은 answer_for 로 어느 문제지의 정답인지 정한다 — 문제지 하나에 정답 파일 하나(새로 올리면 교체)."""
    project = owned(db, m.Project, project_id, user)
    if not rights_confirmed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "학습용으로 쓸 수 있는 자료인지 확인해 주세요")
    target = None
    if kind == "answer_sheet":
        target = owned(db, m.Material, answer_for, user) if answer_for else None
        if target is None or target.project_id != project.id or target.kind == "answer_sheet":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "정답 파일을 붙일 문제지를 골라 주세요")
        if target.status != "ready" or not target.problem_count:
            raise HTTPException(status.HTTP_409_CONFLICT, "문제지의 문항을 다 읽은 뒤에 정답 파일을 올려 주세요")
    if get_llm() is not None:
        quota.check(db, user)
    data = file.file.read()
    if error := materials.validate_upload(file.content_type or "", data):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error)
    if target is not None:
        old = db.scalar(select(m.Material).where(m.Material.answer_for_id == target.id))
        if old is not None:  # 1:1 — 예전 정답 파일은 거두고 지운다
            _remove_material(db, old)
            db.flush()
    material = materials.save_upload(user, project, file.filename or "upload", file.content_type, data, rights_confirmed, kind)
    material.answer_for_id = target.id if target else None
    db.add(material)
    db.commit()
    background.add_task(materials.process, material.id, open_session)
    return MaterialOut.model_validate(material)


@router.get("/{project_id}/materials")
def list_materials(project_id: UUID, user: CurrentUser, db: DB) -> list[MaterialOut]:
    owned(db, m.Project, project_id, user)
    q = select(m.Material).where(m.Material.project_id == project_id).order_by(m.Material.created_at)
    rows = list(db.scalars(q))
    if any([jobs.heal(db, x) for x in rows]):
        db.commit()
    return [MaterialOut.model_validate(x) for x in rows]


@router.get("/{project_id}/workspace")
def project_workspace(project_id: UUID, user: CurrentUser, db: DB) -> dict:
    """프로젝트 작업 공간 — 올린 자료, 그 문항과 1:1 정답(출처·검증 상태)을 한 번에. 올린 사람에게만."""
    project = owned(db, m.Project, project_id, user)
    mats = list(db.scalars(select(m.Material).where(m.Material.project_id == project.id).order_by(m.Material.created_at)))
    if any([jobs.heal(db, x) for x in mats]):
        db.commit()
    sheet_ids = [x.id for x in mats if x.kind != "answer_sheet"]
    problems = list(db.scalars(select(m.Problem).where(m.Problem.material_id.in_(sheet_ids), m.Problem.owner_user_id == user.id)
                                .order_by(m.Problem.created_at))) if sheet_ids else []
    rows = {r.problem_id: r for r in db.scalars(select(m.ProblemAnswer).where(
        m.ProblemAnswer.problem_id.in_([x.id for x in problems])))} if problems else {}
    out = []
    for p in problems:
        row, meta = rows.get(p.id), p.generation_meta or {}
        if row and row.manual_answer:
            source = "manual"
        elif row and row.sheet_answer:
            source = "file" if row.sheet_material_id else "printed"
        elif row and row.ai_answer:
            source = "ai"
        else:
            source = None
        out.append({
            "id": p.id, "material_id": str(p.material_id), "number": answer_key.number_of(p), "stem": p.stem,
            "choices": p.choices, "problem_type": p.problem_type, "difficulty": p.difficulty, "concept_ids": p.concept_ids,
            "needs_figure": bool(meta.get("needs_figure")),
            "answer": p.answer or (row.ai_answer if row else "") or "", "answer_source": source,
            "answer_status": (row.status if row else None) or ("sheet" if p.answer else None),
            "manual": bool(row and row.manual_answer is not None), "page": meta.get("page"), "domain": p.domain,
            "has_solution": bool(row and (row.ai_solution or row.sheet_explanation)),
        })
    out.sort(key=lambda x: (x["material_id"], x["number"] if x["number"] is not None else 10_000))
    return {"materials": [MaterialOut.model_validate(x).model_dump(mode="json") for x in mats], "problems": out}


@router.get("/{project_id}/past-problems")
def list_past_problems(project_id: UUID, user: CurrentUser, db: DB) -> list[PastProblemOut]:
    project = owned(db, m.Project, project_id, user)
    out = []
    for p in tutor.project_past_problems(db, user, project):
        meta = p.generation_meta or {}
        out.append(PastProblemOut(**{k: getattr(p, k) for k in ("id", "domain", "concept_ids", "difficulty", "problem_type", "stem", "choices")},
                                  number=meta.get("number"), has_answer=bool(p.answer), needs_figure=bool(meta.get("needs_figure"))))
    return out


material_router = APIRouter(prefix="/materials", tags=["프로젝트"])


def _remove_material(db: Session, material: m.Material) -> None:
    if material.kind == "answer_sheet":
        answer_key.unmap_answer_sheet(db, material)  # 그 파일에서 온 정답만 거둔다
    else:
        sheet = db.scalar(select(m.Material).where(m.Material.answer_for_id == material.id))
        if sheet is not None:
            (materials.UPLOAD_DIR / sheet.storage_path).unlink(missing_ok=True)
        db.execute(delete(m.Problem).where(m.Problem.material_id == material.id, m.Problem.source == "past_exam"))
    (materials.UPLOAD_DIR / material.storage_path).unlink(missing_ok=True)
    db.delete(material)


@material_router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(material_id: UUID, user: CurrentUser, db: DB) -> Response:
    """올린 파일과 거기서 뽑은 기출 문제를 지운다 (그것으로 새로 만든 문제와 풀이 기록은 남는다).
    문제지를 지우면 붙어 있던 정답 파일도 함께, 정답 파일만 지우면 그 정답만 거둔다."""
    _remove_material(db, owned(db, m.Material, material_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 매핑 편집 (ERD) · 원본 파일 ----------
class ProblemEdit(BaseModel):
    """manual_answer: 직접 고친 정답 (빈 문자열이면 정답 없음으로 고정, null 이면 직접 고친 것 취소). number: 문항 번호."""
    manual_answer: str | None = Field(default=None, max_length=200)
    reset_manual: bool = False
    number: int | None = Field(default=None, ge=0, le=9999)


@material_router.patch("/{material_id}/problems/{problem_id}")
def edit_problem(material_id: UUID, problem_id: str, body: ProblemEdit, user: CurrentUser, db: DB) -> dict:
    """매핑 화면에서 문항의 정답이나 번호를 고친다. 번호를 고치면 연결된 정답 파일과 다시 맞춘다."""
    material = owned(db, m.Material, material_id, user)
    p = db.get(m.Problem, problem_id)
    if p is None or p.material_id != material.id or p.owner_user_id != user.id:
        raise HTTPException(404, "문항을 찾을 수 없어요")
    row = answer_key.row_of(db, p)
    if body.reset_manual:
        row.manual_answer = None
    elif body.manual_answer is not None:
        value = answer_key.normalize(p, body.manual_answer) if body.manual_answer.strip() else ""
        if body.manual_answer.strip() and not value:
            raise HTTPException(422, f"보기 번호(1~{len(p.choices)})로 적어 주세요" if p.choices else "정답을 적어 주세요")
        row.manual_answer = value or None
    remapped = None
    if body.number is not None and body.number != answer_key.number_of(p):
        meta = dict(p.generation_meta or {})
        meta["number"] = body.number
        p.generation_meta = meta
        row.number = body.number
        db.flush()
        remapped = answer_key.remap(db, material)
    answer_key.refresh(p, row)
    db.commit()
    return {"answer": p.answer, "status": row.status, "number": answer_key.number_of(p), "remapped": remapped}


@material_router.get("/{material_id}/file")
def material_file(material_id: UUID, user: CurrentUser, db: DB) -> FileResponse:
    """올린 원본 파일 (올린 사람만) — 그림 문항을 원본에서 볼 때."""
    material = owned(db, m.Material, material_id, user)
    path = materials.UPLOAD_DIR / material.storage_path
    if not path.exists():
        raise HTTPException(404, "원본 파일이 없어요")
    return FileResponse(path, media_type=material.content_type, headers={"Cache-Control": "private, max-age=600"})


# ---------- 정답지 ----------
@material_router.post("/{material_id}/answer-key", status_code=status.HTTP_202_ACCEPTED)
def start_answer_key(material_id: UUID, user: CurrentUser, db: DB, background: BackgroundTasks,
                     open_session=Depends(session_factory)) -> MaterialOut:
    """올린 자료의 모든 문항에 정답과 단계별 해설을 붙인다 (백그라운드, 문항 수에 따라 1~3분). 다시 부르면 새로 만든다."""
    material = owned(db, m.Material, material_id, user)
    jobs.heal(db, material)
    if material.status != "ready" or not material.problem_count:
        raise HTTPException(status.HTTP_409_CONFLICT, "문항을 다 읽은 자료만 정답지를 만들 수 있어요")
    if material.answer_key_status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "정답지를 만들고 있어요. 잠시만 기다려 주세요")
    if get_llm() is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 설정되지 않아 정답지를 만들 수 없어요")
    quota.check(db, user)
    material.answer_key_status, material.answer_key_error = "running", None
    material.answer_key_started_at = func.now()
    db.commit()
    background.add_task(answer_key.build, material.id, open_session)
    return MaterialOut.model_validate(material)


@material_router.get("/{material_id}/answer-key")
def get_answer_key(material_id: UUID, user: CurrentUser, db: DB) -> dict:
    material = owned(db, m.Material, material_id, user)
    if jobs.heal(db, material):
        db.commit()
    return answer_key.view(db, material)


@material_router.post("/{material_id}/ask")
def ask_about_answer_key(material_id: UUID, body: AskIn, user: CurrentUser, db: DB) -> dict:
    """정답지의 문항·해설에서 고른 부분에 대해 묻는다 ('더 자세히', '그래프로' 등). 풀이·그래프·검산 형식으로 답한다."""
    material = owned(db, m.Material, material_id, user)
    problem = db.get(m.Problem, body.problem_id)
    if problem is None or problem.material_id != material.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "문항을 찾을 수 없어요")
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 설정되지 않아 답변할 수 없어요")
    quota.check(db, user)
    row = db.get(m.ProblemAnswer, problem.id)
    no = answer_key.number_of(problem)
    lines = [f"{no}번 문항: {problem.stem}" if no is not None else f"문항: {problem.stem}"]
    if problem.choices:
        lines.append("보기: " + " / ".join(f"{k + 1}) {c}" for k, c in enumerate(problem.choices)))
    answer = problem.answer or (row.ai_answer if row else "")
    if answer:
        lines.append(f"정답: {answer}")
    if row and row.sheet_explanation:
        lines.append(f"정답 파일 해설: {row.sheet_explanation}")
    if row and row.ai_solution:
        lines.append(f"해설: {row.ai_solution}")
    try:
        line, payload = explain.ask_about(db, llm, user, question=body.question.strip(), quote=body.quote.strip(),
                                          context="\n".join(lines), history=[(t.q, t.a) for t in body.history])
    except LLMError as e:
        db.commit()  # 실패한 호출 기록은 남긴다
        log.warning("정답지 질문 답변 실패: %s", e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "답변을 만들지 못했어요. 잠시 후 다시 시도해 주세요") from e
    db.commit()
    return {"line": line, "explanation": payload}


# ---------- 기출 기반 문제 만들기 ----------
LEVEL_LABEL = {"easier": "쉽게", "same": "비슷하게", "harder": "어렵게"}
LEVEL_SHIFT = {"easier": -1, "same": 0, "harder": 1}


@router.post("/{project_id}/generate", status_code=status.HTTP_201_CREATED)
def generate_from_past(project_id: UUID, body: GenerateIn, user: CurrentUser, db: DB) -> SessionDetail:
    """기출을 본보기로 새 문제를 만들어, 결과를 이 프로젝트의 새 대화로 돌려준다 (1~2분 걸릴 수 있음)."""
    project = owned(db, m.Project, project_id, user)
    llm = get_llm()
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 가 아직 설정되지 않았어요")
    quota.check(db, user)
    past = tutor.project_past_problems(db, user, project)
    scope_ids = {c.id for c in materials.scope_concepts(db, project)}

    # 개념: 지정한 것 → 기출에 가장 많이 나온 것 → 이 프로젝트의 약점 → 범위의 첫 개념
    concept_id = body.concept_id
    if concept_id is None and past:
        tagged = [c for p in past for c in p.concept_ids if c in scope_ids]
        concept_id = Counter(tagged).most_common(1)[0][0] if tagged else None
    if concept_id is None:
        weak = [w.concept_id for w in learning.concept_stats(db, user, project_id=project.id) if w.concept_id in scope_ids]
        concept_id = weak[0] if weak else (sorted(scope_ids)[0] if scope_ids else None)
    if concept_id not in scope_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "이 프로젝트 범위의 개념을 골라 주세요")

    exemplars = [p for p in past if concept_id in p.concept_ids] or past
    base = round(sum(p.difficulty for p in exemplars[:3]) / len(exemplars[:3])) if exemplars else 3
    difficulty = min(5, max(1, base + LEVEL_SHIFT[body.level]))
    # 형식·보기 개수는 코스가 아니라 올린 기출대로 (예: 고등 미적분 코스에 편입 4지선다 기출)
    formats, choice_count = generator.past_format(past)
    try:
        report = generator.generate_problems(
            db, llm, concept_id=concept_id, difficulty=difficulty, count=body.count, user=user,
            question_type=project.question_type, exemplars=exemplars, owner=user if exemplars else None,
            textbook=tutor.textbook_label(project), choice_count=choice_count,
            formats=formats if project.question_type == "auto" else None)
    except LLMError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "AI 응답이 원활하지 않아요. 잠시 후 다시 시도해 주세요") from None
    if not report.accepted:
        log.warning("기출 기반 생성 전부 탈락 (project %s): %s", project.id, report.reasons)
        why = Counter(r.split(":")[0] for r in report.reasons).most_common(1)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "만든 문제가 모두 검증을 통과하지 못했어요"
                            + (f" (주된 이유: {why[0][0]})" if why else "") + ". 다시 시도해 주세요")

    concept = db.get(m.Concept, concept_id)
    label = LEVEL_LABEL[body.level]
    basis = f"올린 기출 {min(len(exemplars), 3)}문제를 본보기로" if exemplars else "기출이 없어서 프로젝트 범위를 바탕으로"
    s = m.ChatSession(user_id=user.id, project_id=project.id, title=f"기출 기반 · {concept.name} {label}")
    db.add(s)
    db.flush()
    db.add_all([
        m.Message(session_id=s.id, role="user", text=f"기출보다 {label} {body.count}문제 만들어 줘"),
        m.Message(session_id=s.id, role="ai", problem_ids=report.accepted,
                  text=f"{basis} '{concept.name}' 문제 {len(report.accepted)}개를 {label} 만들고 검증했어요."
                       + (f" (검증을 통과하지 못한 {len(report.rejected)}문제는 뺐어요)" if report.rejected else "")),
    ])
    db.commit()
    return session_detail(db, user, s)
