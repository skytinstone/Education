"""초기 데이터 적재 — 개념 트리와 문제 은행(여러 번 실행해도 안전), 선택적으로 데모 사용자.

    uv run python -m education.seed            # 개념 + 문제 은행
    uv run python -m education.seed --demo     # + 데모 계정 (demo@example.com / eureka-demo)
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from education.concepts import load_concept_tree
from education.db import models as m
from education.schemas import ConceptLevel, ErrorType, Problem, ProblemSource, VerificationStatus
from education.security import hash_password

ROOT = Path(__file__).resolve().parents[2]
PROBLEM_FILE = ROOT / "data" / "problems" / "sample.yaml"
LEVEL_ORDER = {ConceptLevel.SUBJECT: 0, ConceptLevel.UNIT: 1, ConceptLevel.CONCEPT: 2}


def seed_concepts(db: Session) -> int:
    concepts = sorted(load_concept_tree(), key=lambda c: (LEVEL_ORDER[c.level], c.id))  # 부모 먼저
    for c in concepts:
        row = {"id": c.id, "name": c.name, "domain": c.domain, "level": c.level,
               "parent_id": c.parent_id, "prerequisites": c.prerequisites}
        db.execute(insert(m.Concept).values(row).on_conflict_do_update(index_elements=["id"], set_=row))
    return len(concepts)


def load_problem_file(path: Path = PROBLEM_FILE) -> list[Problem]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["problems"]
    # Pydantic 스키마로 검증 (보기 5개, 정답 번호 범위 등)
    return [Problem(**p, source=ProblemSource.CURATED, verification=VerificationStatus.VERIFIED) for p in raw]


def seed_problems(db: Session) -> int:
    problems = load_problem_file()
    for p in problems:
        row = p.model_dump(include={"id", "domain", "difficulty", "problem_type", "stem", "choices",
                                    "answer", "solution", "traps", "source", "verification"})
        db.execute(insert(m.Problem).values(row).on_conflict_do_update(index_elements=["id"], set_=row))
        db.execute(delete(m.ProblemConcept).where(m.ProblemConcept.problem_id == p.id))
        db.execute(insert(m.ProblemConcept), [{"problem_id": p.id, "concept_id": c} for c in p.concept_ids])
    return len(problems)


DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "eureka-demo"


def seed_demo_user(db: Session) -> m.User:
    """프로토타입(store.js)과 같은 샘플 데이터를 가진 데모 계정. 이미 있으면 지우고 다시 만든다."""
    db.execute(delete(m.User).where(m.User.email == DEMO_EMAIL))
    user = m.User(email=DEMO_EMAIL, name="민석", password_hash=hash_password(DEMO_PASSWORD))
    db.add(user)
    db.flush()

    now = datetime.now(timezone.utc)
    at = lambda days, hours=0: now - timedelta(days=days, hours=hours)  # noqa: E731
    today = date.today()

    projects = {
        "math": m.Project(user_id=user.id, name="2027 수능 미적분", subject_id="math.calculus", goal="1등급", exam_date=today + timedelta(days=24), created_at=at(20)),
        "chemistry": m.Project(user_id=user.id, name="화학I 중간고사", subject_id="chemistry.chemistry1", goal="90점 이상", exam_date=today + timedelta(days=12), created_at=at(15)),
        "physics": m.Project(user_id=user.id, name="물리 역학 기초 다지기", subject_id="physics.physics1", unit_ids=["physics.physics1.mechanics_energy"], created_at=at(9)),
    }
    db.add_all(projects.values())
    db.flush()

    def session(project, title, days, ask, problem_ids):
        s = m.ChatSession(user_id=user.id, project_id=project.id if project else None, title=title, created_at=at(days, 1), updated_at=at(days))
        s.messages = [
            m.Message(role="user", text=ask, created_at=at(days, 1)),
            m.Message(role="ai", text="AI 연결 전이라 문제 은행의 샘플 문제를 보여드려요.", problem_ids=problem_ids, created_at=at(days)),
        ]
        db.add(s)

    session(projects["math"], "치환적분 변형 문제", 0, "치환적분 3점짜리 문제 내줘", ["pb_subst", "pb_defint"])
    session(projects["chemistry"], "중화반응 왜 틀렸는지", 0.4, "중화반응 문제 다시 풀어볼래", ["pb_neut", "pb_mole"])
    session(None, "로그 성질 개념 정리", 1, "로그 성질 문제 하나 내줘", ["pb_log"])
    session(projects["math"], "6월 모의고사 약점 분석", 3, "수열이랑 확률 문제 섞어서 내줘", ["pb_seq", "pb_cond"])
    session(None, "H-R도 암기 카드 만들기", 5, "H-R도 문제 내줘", ["pb_hr", "pb_half"])
    session(projects["physics"], "등가속도 운동 그래프 문제", 10, "등가속도 운동 문제 내줘", ["pb_kin", "pb_mom"])

    # 최근 7일 풀이 기록 (프로토타입과 같은 규칙)
    bank = {p.id: p for p in load_problem_file()}
    ids = list(bank)
    for d in range(6, -1, -1):
        for i in range(12 if d == 0 else 6):
            pid = ids[(i * 5 + d * 3) % len(ids)]
            project = projects.get(bank[pid].domain)
            db.add(m.Attempt(user_id=user.id, problem_id=pid, project_id=project.id if project else None,
                             answer="", correct=(i + d) % 3 != 0, created_at=at(d, 10 - i * 0.5)))

    db.add_all([
        m.WrongNote(user_id=user.id, problem_id="pb_subst", project_id=projects["math"].id, answer="2", error_type=ErrorType.CALCULATION, created_at=at(0, 2)),
        m.WrongNote(user_id=user.id, problem_id="pb_defint", project_id=projects["math"].id, answer="1", error_type=ErrorType.CONCEPT_GAP, created_at=at(2)),
        m.WrongNote(user_id=user.id, problem_id="pb_neut", project_id=projects["chemistry"].id, answer="3", error_type=ErrorType.MISAPPLICATION, created_at=at(3)),
        m.WrongNote(user_id=user.id, problem_id="pb_hr", answer="1", error_type=ErrorType.CONCEPT_GAP, created_at=at(6), resolved_at=at(4)),
    ])

    cards = [
        ("math.math1.exp_log.log_properties", "로그의 밑 변환 공식", "log_a b = log_c b ÷ log_c a"),
        ("math.math1.exp_log.log_properties", "log_a (MN) = ?", "log_a M + log_a N"),
        ("chemistry.chemistry1.atomic_world.periodic_trends", "같은 주기에서 원자 번호가 커지면 원자 반지름은?", "작아진다 (유효 핵전하가 커지기 때문)"),
        ("chemistry.chemistry1.atomic_world.periodic_trends", "같은 족에서 아래로 갈수록 이온화 에너지는?", "작아진다 (전자 껍질 수가 늘어나기 때문)"),
        ("earth_science.earth1.space.stellar_properties", "H-R도 왼쪽 위에 있는 별의 특징은?", "표면 온도가 높고 광도가 크다"),
        ("earth_science.earth1.space.stellar_properties", "백색 왜성은 H-R도의 어디에 있나?", "왼쪽 아래 (온도는 높고 광도는 작다)"),
        ("physics.physics1.mechanics_energy.momentum_impulse", "운동량의 정의는?", "p = mv (방향이 있는 벡터량)"),
        ("physics.physics1.mechanics_energy.momentum_impulse", "충격량과 운동량의 관계는?", "충격량 = 운동량의 변화량 (FΔt = Δp)"),
    ]
    db.add_all(m.Card(user_id=user.id, concept_id=c, front=f, back=b, created_at=at(0, -i)) for i, (c, f, b) in enumerate(cards))
    db.add_all([m.SavedProblem(user_id=user.id, problem_id=pid) for pid in ("pb_log", "pb_kin")])
    db.flush()
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="데모 계정과 샘플 학습 기록도 만든다")
    args = parser.parse_args()

    from education.db.session import SessionLocal

    with SessionLocal.begin() as db:
        print(f"개념 {seed_concepts(db)}개")
        print(f"문제 {seed_problems(db)}개")
        if args.demo:
            seed_demo_user(db)
            print(f"데모 계정: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
