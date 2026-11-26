"""문제 성적표 — 학생 풀이 기록으로 문제마다 품질을 매긴다 (문항 분석).

학생마다 실력이 다르므로 단순 정답률만 보지 않는다. 라쉬(Rasch) 모형으로 '학생 실력 θ' 와 '문제 난이도 b' 를
함께 추정한다 — 약한 학생만 풀어서 정답률이 낮은 문제를 '어렵다' 고 잘못 판단하지 않도록.

    P(맞힘) = 1 / (1 + exp(-(θ - b)))   · 분야(수학·물리…)마다 따로 추정 · 학생 평균 θ = 0

문제마다:
- 실제 난이도: 평균 실력 학생의 예상 정답률 σ(-b) 를 1~5 로 바꾼 값 → 의도한 난이도와 비교
- 변별도: 맞힘 여부와 학생 실력의 상관 (잘하는 학생이 맞히고 약한 학생이 틀리면 높음, 0 아래면 문제 결함 의심)
- 보기 분석(객관식): 보기마다 고른 비율과 고른 학생의 평균 실력 → 아무도 안 고르는 '죽은 보기',
  잘하는 학생이 정답보다 더 고른 '정답 의심' 보기
- 등급 A~D 와 표시(flags)

한 학생이 한 문제를 처음 푼 기록만 쓴다 (다시 풀기·복습은 이미 답을 본 뒤라 섞지 않음).
결과는 problem_stats 에 저장하고, 문제 생성 프롬프트가 개념별 요약(concept_feedback)을 참고한다.
다른 학생이 누구인지는 어디에도 내보내지 않고 합친 수치만 쓴다.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from education.db import models as m

MIN_N = 5  # 이만큼 풀려야 성적을 매긴다
CHOICE_MIN_N = 15  # 보기 분석은 이만큼부터
DEAD_SHARE = 0.03
ITERATIONS = 40
CLIP = 4.0

FLAG_NAME = {
    "harder_than_meant": "의도보다 어려움",
    "easier_than_meant": "의도보다 쉬움",
    "too_easy": "거의 다 맞힘",
    "too_hard": "거의 다 틀림",
    "low_disc": "변별력 낮음",
    "neg_disc": "잘하는 학생이 더 틀림",
    "dead_choice": "아무도 안 고르는 보기",
    "key_suspect": "정답 의심",
}


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def observed_level(b: float) -> int:
    """평균 실력 학생의 예상 정답률로 1~5 단계."""
    p = _sigmoid(-b)
    return 1 if p >= 0.85 else 2 if p >= 0.7 else 3 if p >= 0.5 else 4 if p >= 0.3 else 5


@dataclass
class Item:
    id: str
    domain: str
    difficulty: int
    choices: list[str] | None
    answer: str
    resp: list[tuple[object, bool, str]] = field(default_factory=list)  # (학생, 맞힘, 답)


def rasch(items: dict[str, Item]) -> tuple[dict[object, float], dict[str, float]]:
    """한 분야의 학생 실력 θ 와 문제 난이도 b (결합 최대우도, 뉴턴 방법 · 값은 ±4 로 자름)."""
    theta: dict[object, float] = defaultdict(float)
    by_user: dict[object, list[tuple[str, bool]]] = defaultdict(list)
    b: dict[str, float] = {}
    for it in items.values():
        n = len(it.resp)
        k = sum(1 for _, x, _ in it.resp if x)
        b[it.id] = -math.log((k + 0.5) / (n - k + 0.5))
        for u, x, _ in it.resp:
            by_user[u].append((it.id, x))
    for _ in range(ITERATIONS):
        for u, rs in by_user.items():
            g = h = 0.0
            for i, x in rs:
                p = _sigmoid(theta[u] - b[i])
                g += x - p
                h += p * (1 - p)
            theta[u] = max(-CLIP, min(CLIP, theta[u] + max(-1.0, min(1.0, g / max(h, 1e-6)))))
        for it in items.values():
            g = h = 0.0
            for u, x, _ in it.resp:
                p = _sigmoid(theta[u] - b[it.id])
                g += x - p
                h += p * (1 - p)
            b[it.id] = max(-CLIP, min(CLIP, b[it.id] - max(-1.0, min(1.0, g / max(h, 1e-6)))))
        mean = sum(theta.values()) / len(theta) if theta else 0.0  # 학생 평균을 0 에 맞춘다
        for u in theta:
            theta[u] -= mean
        for i in b:
            b[i] -= mean
    return dict(theta), b


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def analyze(it: Item, b: float, theta: dict[object, float]) -> dict:
    n = len(it.resp)
    k = sum(1 for _, x, _ in it.resp if x)
    p = k / n
    disc = _corr([theta[u] for u, _, _ in it.resp], [1.0 if x else 0.0 for _, x, _ in it.resp])
    level = observed_level(b)
    flags: list[str] = []
    if level - it.difficulty >= 2:
        flags.append("harder_than_meant")
    elif it.difficulty - level >= 2:
        flags.append("easier_than_meant")
    if p >= 0.95 and n >= 10:
        flags.append("too_easy")
    if p <= 0.05 and n >= 10:
        flags.append("too_hard")
    if disc is not None:
        if disc < 0:
            flags.append("neg_disc")
        elif disc < 0.15:
            flags.append("low_disc")

    choices = None
    if it.choices:
        stats = [{"n": 0, "ability": None} for _ in it.choices]
        abil: list[list[float]] = [[] for _ in it.choices]
        for u, _, ans in it.resp:
            if ans.isdigit() and 1 <= int(ans) <= len(it.choices):
                stats[int(ans) - 1]["n"] += 1
                abil[int(ans) - 1].append(theta[u])
        for s, a in zip(stats, abil):
            s["ability"] = round(sum(a) / len(a), 2) if a else None
        choices = stats
        key = int(it.answer) - 1 if it.answer.isdigit() and 1 <= int(it.answer) <= len(it.choices) else None
        if n >= CHOICE_MIN_N and key is not None:
            wrong = [i for i in range(len(stats)) if i != key]
            if any(stats[i]["n"] / n < DEAD_SHARE for i in wrong):
                flags.append("dead_choice")
            ka = stats[key]["ability"]
            if any(stats[i]["n"] >= stats[key]["n"] and stats[i]["ability"] is not None and ka is not None and stats[i]["ability"] > ka
                   for i in wrong):
                flags.append("key_suspect")

    score = 100
    score -= 40 if "key_suspect" in flags else 0
    score -= 35 if "neg_disc" in flags else 15 if "low_disc" in flags else 0
    score -= 20 if ("harder_than_meant" in flags or "easier_than_meant" in flags) else 0
    score -= 15 if ("too_easy" in flags or "too_hard" in flags) else 0
    score -= 5 if "dead_choice" in flags else 0
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return {"n": n, "p": round(p, 3), "b": round(b, 3), "disc": None if disc is None else round(disc, 3),
            "observed_difficulty": level, "choices": choices, "flags": flags, "grade": grade}


def _first_attempts(db: Session):
    """학생 × 문제마다 처음 푼 기록."""
    first = (select(m.Attempt.user_id, m.Attempt.problem_id, m.Attempt.answer, m.Attempt.correct)
             .distinct(m.Attempt.user_id, m.Attempt.problem_id)
             .order_by(m.Attempt.user_id, m.Attempt.problem_id, m.Attempt.created_at)).subquery()
    return db.execute(select(first.c.user_id, first.c.correct, first.c.answer, m.Problem.id, m.Problem.domain,
                             m.Problem.difficulty, m.Problem.choices, m.Problem.answer)
                      .join(m.Problem, m.Problem.id == first.c.problem_id))


def refresh(db: Session) -> dict:
    """모든 문제의 성적을 다시 계산해 저장한다. 분야마다 θ·b 를 함께 추정."""
    domains: dict[str, dict[str, Item]] = defaultdict(dict)
    for uid, correct, ans, pid, domain, diff, choices, key in _first_attempts(db):
        it = domains[domain].get(pid)
        if it is None:
            it = domains[domain][pid] = Item(pid, domain, diff, choices, key or "")
        it.resp.append((uid, bool(correct), (ans or "").strip()))
    rows = []
    for items in domains.values():
        rated = {i: it for i, it in items.items() if len(it.resp) >= MIN_N}
        if not rated:
            continue
        theta, b = rasch(rated)
        rows += [{"problem_id": i, **analyze(it, b[i], theta)} for i, it in rated.items()]
    db.execute(delete(m.ProblemStats))
    if rows:
        db.add_all(m.ProblemStats(**r) for r in rows)
    db.flush()
    from education.harness import review  # D 등급이나 정답 의심은 사람이 본다
    for r in rows:
        if r["grade"] == "D" or "key_suspect" in r["flags"]:
            review.enqueue(db, r["problem_id"], "item_stats",
                           f"성적 {r['grade']} · " + ", ".join(FLAG_NAME.get(f, f) for f in r["flags"]) + f" · {r['n']}명 풀이")
    grades = defaultdict(int)
    for r in rows:
        grades[r["grade"]] += 1
    return {"problems": len(rows), "grades": dict(grades)}


def concept_feedback(db: Session, concept_id: str, limit: int = 40) -> str:
    """문제 생성 프롬프트에 붙일 '실제 학생 데이터로 본 이 개념의 문제 성적' (없으면 빈 문자열)."""
    S, P = m.ProblemStats, m.Problem
    rows = db.execute(select(S, P.stem, P.choices, P.difficulty).join(P, P.id == S.problem_id)
                      .join(m.ProblemConcept, m.ProblemConcept.problem_id == P.id)
                      .where(m.ProblemConcept.concept_id == concept_id, P.owner_user_id.is_(None))
                      .order_by(S.n.desc()).limit(limit)).all()
    if not rows:
        return ""
    lines = [f"[실제 학생 풀이로 본 이 개념의 기존 문제 {len(rows)}개 — 학생 실력을 감안한 분석]"]
    gap = defaultdict(list)
    for s, _, _, diff in rows:
        gap[diff].append(s.observed_difficulty)
    for diff in sorted(gap):
        obs = sum(gap[diff]) / len(gap[diff])
        if abs(obs - diff) >= 1:
            lines.append(f"- 난이도 {diff}로 낸 문제가 실제로는 평균 {obs:.1f} 수준이었어요 → "
                         + ("더 어렵게 (조건 결합·함정을 늘려서)" if obs < diff else "더 쉽게 (단계를 줄여서)") + " 맞춰 주세요.")
    traps, dead = [], []
    for s, stem, choices, _ in rows:
        if not choices or not s.choices or s.n < CHOICE_MIN_N:
            continue
        for i, c in enumerate(s.choices):
            share = c["n"] / s.n
            if share >= 0.2 and c.get("ability") is not None and c["ability"] < 0 and "key_suspect" not in s.flags:
                traps.append((share, stem, choices[i]))
            elif share < DEAD_SHARE:
                dead.append(choices[i])
    for share, stem, choice in sorted(traps, reverse=True)[:3]:
        lines.append(f"- 효과적이었던 함정: 「{stem[:60]}」의 보기 '{choice[:40]}' — 약한 학생의 {round(share * 100)}%가 골랐어요. 이런 실제 실수를 오답 보기로 쓰세요.")
    if dead:
        lines.append(f"- 아무도 고르지 않은 보기 예: {', '.join(repr(d[:30]) for d in dead[:3])} — 말이 안 되는 보기 대신 실제로 할 법한 실수로 만드세요.")
    bad = [stem for s, stem, _, _ in rows if "neg_disc" in s.flags or "key_suspect" in s.flags]
    if bad:
        lines.append(f"- 잘하는 학생이 오히려 더 틀린 문제가 있었어요 (조건이 모호했을 가능성): 「{bad[0][:80]}」 — 조건을 빠짐없이, 한 가지로만 읽히게 쓰세요.")
    return "\n".join(lines) if len(lines) > 1 else ""


def summary(db: Session, *, flag: str | None = None, grade: str | None = None, limit: int = 100) -> dict:
    S, P = m.ProblemStats, m.Problem
    q = (select(S, P.stem, P.difficulty, P.domain, P.source, P.choices, P.answer)
         .join(P, P.id == S.problem_id))
    if flag:
        q = q.where(S.flags.any(flag))
    if grade:
        q = q.where(S.grade == grade)
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    rows = sorted(db.execute(q).all(), key=lambda r: (-order[r[0].grade], -r[0].n))[:limit]
    grades = dict(db.execute(select(S.grade, func.count()).group_by(S.grade)).all())
    flags = defaultdict(int)
    for (fl,) in db.execute(select(S.flags)):
        for f in fl:
            flags[f] += 1
    updated = db.scalar(select(func.max(S.updated_at)))
    names = dict(db.execute(select(m.ProblemConcept.problem_id, m.Concept.name).join(m.Concept)
                            .where(m.ProblemConcept.problem_id.in_([r[0].problem_id for r in rows]))).all()) if rows else {}
    return {
        "updated_at": updated.isoformat() if updated else None,
        "min_n": MIN_N, "grades": grades, "flags": dict(flags), "flag_names": FLAG_NAME,
        "items": [{
            "problem_id": s.problem_id, "concept": names.get(s.problem_id, ""), "stem": stem[:160], "domain": domain, "source": source,
            "intended": diff, "observed": s.observed_difficulty, "n": s.n, "p": s.p, "disc": s.disc, "grade": s.grade,
            "flags": s.flags, "answer": answer,
            "choices": [{"text": (choices[i] if choices and i < len(choices) else "")[:60], **c} for i, c in enumerate(s.choices or [])],
        } for s, stem, diff, domain, source, choices, answer in rows],
    }
