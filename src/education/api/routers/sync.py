"""화면(prototype/store.js)이 처음 열릴 때 내 데이터를 한 번에 받아 가는 경로.

응답 모양을 store.js 의 상태 구조(camelCase, 시각은 epoch 밀리초)와 똑같이 맞춰,
화면 코드가 브라우저 저장소 대신 서버 데이터를 그대로 쓰게 한다.
정답·해설은 내가 푼 적이 있는 문제만 담는다.
"""

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from education.api.deps import DB, CurrentUser
from education.api.dto import UserOut
from education.db import models as m
from education.schemas import VerificationStatus
from education.services import learning

router = APIRouter(tags=["동기화"])


def ms(t: datetime | None) -> int | None:
    return int(t.timestamp() * 1000) if t else None


@router.get("/sync")
def sync(user: CurrentUser, db: DB) -> dict:
    attempts = list(db.scalars(select(m.Attempt).where(m.Attempt.user_id == user.id).order_by(m.Attempt.created_at)))
    tried = {a.problem_id for a in attempts}
    problems = db.scalars(select(m.Problem).where(learning.visible_to(user), m.Problem.verification != VerificationStatus.REJECTED))
    sessions = db.scalars(select(m.ChatSession).where(m.ChatSession.user_id == user.id))
    return {
        "user": {
            "id": str(user.id), "name": user.name, "email": user.email, "dailyGoal": user.daily_goal,
            "birthDate": user.birth_date.isoformat() if user.birth_date else None, "school": user.school,
            "major": user.major, "address": user.address, "avatarType": user.avatar_type,
            "avatarPreset": user.avatar_preset, "avatarUrl": UserOut.model_validate(user).avatar_url,
        },
        "projects": [{
            "id": str(p.id), "name": p.name, "subjectId": p.subject_id, "unitIds": p.unit_ids, "goal": p.goal,
            "examDate": p.exam_date.isoformat() if p.exam_date else None, "questionType": p.question_type,
            "pinned": p.pinned, "createdAt": ms(p.created_at),
        } for p in db.scalars(select(m.Project).where(m.Project.user_id == user.id))],
        "sessions": [{
            "id": str(s.id), "projectId": str(s.project_id) if s.project_id else None, "title": s.title,
            "createdAt": ms(s.created_at), "updatedAt": ms(s.updated_at),
            "messages": [{"role": x.role, "text": x.text, "problemIds": x.problem_ids, "at": ms(x.created_at)} for x in s.messages],
        } for s in sessions],
        "attempts": [{
            "id": str(a.id), "problemId": a.problem_id, "projectId": str(a.project_id) if a.project_id else None,
            "sessionId": str(a.session_id) if a.session_id else None, "answer": a.answer, "correct": a.correct, "at": ms(a.created_at),
        } for a in attempts],
        "wrongNotes": [{
            "id": str(w.id), "problemId": w.problem_id, "projectId": str(w.project_id) if w.project_id else None,
            "answer": w.answer, "errorType": w.error_type, "createdAt": ms(w.created_at), "resolvedAt": ms(w.resolved_at),
        } for w in db.scalars(select(m.WrongNote).where(m.WrongNote.user_id == user.id))],
        "cards": [{"id": str(c.id), "conceptId": c.concept_id, "front": c.front, "back": c.back, "known": c.known}
                  for c in db.scalars(select(m.Card).where(m.Card.user_id == user.id).order_by(m.Card.created_at))],
        "savedProblemIds": list(db.scalars(select(m.SavedProblem.problem_id).where(m.SavedProblem.user_id == user.id))),
        "problems": [{
            "id": p.id, "domain": p.domain, "conceptIds": p.concept_ids, "difficulty": p.difficulty,
            "problemType": p.problem_type, "stem": p.stem, "choices": p.choices, "source": p.source,
            "answer": p.answer if p.id in tried else None, "solution": p.solution if p.id in tried else None,
        } for p in problems],
    }
