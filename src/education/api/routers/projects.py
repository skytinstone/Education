from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from education.api.deps import DB, CurrentUser, owned
from education.api.dto import ProjectIn, ProjectOut, ProjectPatch, ProjectSummary
from education.db import models as m
from education.schemas import ConceptLevel
from education.services import learning

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
