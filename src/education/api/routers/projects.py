from collections import Counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import (
    GenerateIn, MaterialOut, PastProblemOut, ProjectIn, ProjectOut, ProjectPatch, ProjectSummary, SessionDetail,
)
from education.api.routers.sessions import session_detail
from education.db import models as m
from education.db.session import session_factory
from education.schemas import ConceptLevel
from education.services import generator, learning, materials, tutor
from education.services.llm import LLMError, get_llm

router = APIRouter(prefix="/projects", tags=["프로젝트"])


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
        if v is None and k not in ("exam_date",):
            continue  # exam_date 만 null 로 지울 수 있다
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
                          open_session=Depends(session_factory)) -> MaterialOut:
    """기출·시험지(PDF·사진)를 올리면 백그라운드에서 AI 가 문제를 뽑는다. 상태는 GET 으로 확인."""
    project = owned(db, m.Project, project_id, user)
    if not rights_confirmed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "학습용으로 쓸 수 있는 자료인지 확인해 주세요")
    data = file.file.read()
    if error := materials.validate_upload(file.content_type or "", data):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error)
    material = materials.save_upload(user, project, file.filename or "upload", file.content_type, data, rights_confirmed)
    db.add(material)
    db.commit()
    background.add_task(materials.process, material.id, open_session)
    return MaterialOut.model_validate(material)


@router.get("/{project_id}/materials")
def list_materials(project_id: UUID, user: CurrentUser, db: DB) -> list[MaterialOut]:
    owned(db, m.Project, project_id, user)
    q = select(m.Material).where(m.Material.project_id == project_id).order_by(m.Material.created_at)
    return [MaterialOut.model_validate(x) for x in db.scalars(q)]


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


@material_router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(material_id: UUID, user: CurrentUser, db: DB) -> Response:
    """올린 파일과 거기서 뽑은 기출 문제를 지운다 (그것으로 새로 만든 문제와 풀이 기록은 남는다)."""
    material = owned(db, m.Material, material_id, user)
    db.execute(delete(m.Problem).where(m.Problem.material_id == material.id, m.Problem.source == "past_exam"))
    (materials.UPLOAD_DIR / material.storage_path).unlink(missing_ok=True)
    db.delete(material)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    try:
        report = generator.generate_problems(
            db, llm, concept_id=concept_id, difficulty=difficulty, count=body.count, user=user,
            question_type=project.question_type, exemplars=exemplars, owner=user if exemplars else None)
    except LLMError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "AI 응답이 원활하지 않아요. 잠시 후 다시 시도해 주세요") from None
    if not report.accepted:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "만든 문제가 모두 검증을 통과하지 못했어요. 다시 시도해 주세요")

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
