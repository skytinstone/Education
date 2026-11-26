"""정답지 — 올린 문제지의 문항마다 정답과 단계별 해설을 붙이고, 정답 파일과 1:1 로 맞춘다.

정답은 문항당 한 행(problem_answers)에 출처별로 모은다.
- sheet_answer: 문제지에 인쇄돼 있던 정답 또는 따로 올린 정답 파일(answer_sheet)의 정답 — 번호로 문항과 1:1 매칭
- ai_answer·ai_solution: AI 가 직접 푼 답과 해설
- check_answer: 정답을 모르는 채 다시 푼 답 (정답표가 없을 때만)

상태(refresh): 정답표 있음 → AI 풀이와 같으면 confirmed, 다르면 conflict / 정답표 없음 → 두 번 푼 답이 같으면 verified,
다르면 uncertain / 정답표만 있고 풀이 전이면 sheet. 확실한 문항만 problems.answer 를 채워 학생 연습에 쓴다.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from education.harness import prompts
from education.config import get_settings
from education.db import models as m
from education.schemas import VerificationStatus
from education.services import learning, notifications
from education.services.llm import LLM, Attachment, LLMError, Usage, get_llm

log = logging.getLogger(__name__)

BATCH = 5
WORKERS = 3
CIRCLED = {c: str(i) for i, c in enumerate("①②③④⑤⑥⑦⑧⑨", 1)}


class Solved(BaseModel):
    idx: int = Field(description="문항 번호표의 idx")
    answer: str = Field(description="객관식이면 보기 번호(1부터)만, 그 외에는 답만 (단위·설명 없이)")
    solution: str = Field(description="해요체 단계별 해설. 단계마다 줄을 바꾸고 '1) …' 처럼 번호를 붙인다. 수식은 $...$ (LaTeX)")


class SolveBatch(BaseModel):
    items: list[Solved]


class Checked(BaseModel):
    idx: int
    answer: str = Field(description="객관식이면 보기 번호(1부터)만, 그 외에는 답만")


class CheckBatch(BaseModel):
    items: list[Checked]


SOLVE_INSTRUCTIONS = prompts.text("answer_key.solve_instructions")  # harness/prompts/answer_key/solve_instructions.md

CHECK_INSTRUCTIONS = prompts.text("answer_key.check_instructions")  # harness/prompts/answer_key/check_instructions.md


# ---------- 문항 ↔ 정답 행 ----------
def number_of(p: m.Problem) -> int | None:
    n = (p.generation_meta or {}).get("number")
    return n if isinstance(n, int) else None


def problems_of(db: Session, material: m.Material) -> list[m.Problem]:
    rows = list(db.scalars(select(m.Problem).where(m.Problem.material_id == material.id).order_by(m.Problem.created_at)))
    return sorted(rows, key=lambda p: number_of(p) if number_of(p) is not None else 10_000)


def row_of(db: Session, p: m.Problem) -> m.ProblemAnswer:
    """문항의 정답 행 (없으면 만든다 — 문항 하나에 정답 행 하나)."""
    row = db.get(m.ProblemAnswer, p.id)
    if row is None:
        row = m.ProblemAnswer(problem_id=p.id, material_id=p.material_id, number=number_of(p), sheet_answer="")
        db.add(row)
    return row


def _mc_answer(text: str, n: int) -> str:
    t = "".join(CIRCLED.get(ch, ch) for ch in text or "")
    hit = re.search(r"\d+", t)
    return hit.group(0) if hit and 1 <= int(hit.group(0)) <= n else ""


def normalize(p: m.Problem, answer: str | None) -> str:
    return _mc_answer(answer or "", len(p.choices)) if p.choices else (answer or "").strip()[:200]


def same(p: m.Problem, a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if p.choices:
        return a == b
    x, y = learning.parse_number(a), learning.parse_number(b)
    if x is not None and y is not None and re.fullmatch(r"[-\d.,/eE\s]+", a) and re.fullmatch(r"[-\d.,/eE\s]+", b):
        return learning.numbers_match(x, y, 0)
    return learning.norm_text(a) == learning.norm_text(b)


def refresh(p: m.Problem, row: m.ProblemAnswer) -> None:
    """정답 행에서 상태와 문항의 정답·공개 여부를 다시 계산한다."""
    figure = bool((p.generation_meta or {}).get("needs_figure"))
    if row.manual_answer:
        row.status, p.answer = "manual", row.manual_answer
        if row.ai_solution:
            p.solution = row.ai_solution
        p.verification = VerificationStatus.PENDING if figure else VerificationStatus.VERIFIED
        return
    if row.status == "failed" and not row.ai_answer and not row.sheet_answer:
        p.answer, p.verification = "", VerificationStatus.PENDING
        return
    if row.sheet_answer:
        row.status = ("confirmed" if same(p, row.sheet_answer, row.ai_answer) else "conflict") if row.ai_answer else "sheet"
        p.answer = row.sheet_answer
        ok = row.status != "conflict"
    elif row.ai_answer:
        row.status = "verified" if same(p, row.ai_answer, row.check_answer) else "uncertain"
        p.answer = row.ai_answer if row.status == "verified" else ""
        ok = row.status == "verified"
    else:
        row.status, p.answer, ok = (None if row.status in (None, "manual") else row.status), "", False
    if row.ai_solution:
        p.solution = row.ai_solution
    # 확실한 정답이 있고 그림 없이 풀 수 있는 문항만 학생 연습에 낸다
    p.verification = VerificationStatus.VERIFIED if ok and p.answer and not figure else VerificationStatus.PENDING


# ---------- 정답지 만들기 ----------
def _question_text(i: int, p: m.Problem) -> str:
    meta = p.generation_meta or {}
    head = f"[idx {i}]" + (f" ({meta['number']}번)" if meta.get("number") else "") + (" [그림 필요]" if meta.get("needs_figure") else "")
    body = p.stem
    if p.choices:
        body += "\n" + "\n".join(f"{k}) {c}" for k, c in enumerate(p.choices, 1))
    else:
        body += "\n(단답형 · 답만)"
    return f"{head}\n{body}"


def _log(db: Session, purpose: str, user_id, u: Usage | None, error: str | None = None) -> None:
    s = get_settings()
    if u is None:
        db.add(m.LLMCall(purpose=purpose, model=s.openai_model_generate, ok=False, error=error, user_id=user_id))
        return
    db.add(m.LLMCall(purpose=purpose, model=u.model, ok=True, user_id=user_id, cost_usd=u.cost_usd,
                     input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                     reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))


def build(material_id: uuid.UUID, open_session: Callable[[], AbstractContextManager[Session]], llm: LLM | None = None) -> None:
    """백그라운드에서 실행: 문제지의 모든 문항에 정답과 해설을 붙인다. 묶음이 끝날 때마다 진행률을 저장한다."""
    llm = llm or get_llm()
    s = get_settings()
    with open_session() as db:
        material = db.get(m.Material, material_id)
        if material is None:
            return
        if llm is None:
            material.answer_key_status, material.answer_key_error = "failed", "AI 가 설정되지 않아 정답지를 만들 수 없어요"
            db.commit()
            return
        problems = problems_of(db, material)
        rows = {p.id: row_of(db, p) for p in problems}
        material.answer_key_done = 0
        db.commit()
        from education.services.materials import UPLOAD_DIR  # 순환 import 방지
        path = UPLOAD_DIR / material.storage_path
        file = Attachment(data=path.read_bytes(), mime=material.content_type, filename=material.filename) if path.exists() else None

        chunks = [problems[i:i + BATCH] for i in range(0, len(problems), BATCH)]

        def run(chunk):
            texts = [_question_text(i, p) for i, p in enumerate(chunk, 1)]
            unsure = [i for i, p in enumerate(chunk, 1) if not rows[p.id].sheet_answer]
            files = [file] if file and any((p.generation_meta or {}).get("needs_figure") for p in chunk) else None
            out = {"solve": None, "check": None, "errors": []}
            try:
                out["solve"] = llm.structured(model=s.openai_model_generate, effort=s.openai_effort_generate,
                                              instructions=SOLVE_INSTRUCTIONS, prompt="\n\n".join(texts),
                                              schema=SolveBatch, max_output_tokens=32000, files=files)
            except LLMError as e:
                out["errors"].append(("answer_key", str(e)))
                return out
            if unsure:
                try:
                    out["check"] = llm.structured(model=s.openai_model_verify, effort=s.openai_effort_verify,
                                                  instructions=CHECK_INSTRUCTIONS, prompt="\n\n".join(texts[i - 1] for i in unsure),
                                                  schema=CheckBatch, max_output_tokens=8000, files=files)
                except LLMError as e:
                    out["errors"].append(("answer_verify", str(e)))
            return out

        solved_any = False
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(run, chunk): chunk for chunk in chunks}
            for fut in as_completed(futures):  # 끝난 묶음부터 저장 → 화면이 진행률을 볼 수 있다
                chunk, res = futures[fut], fut.result()
                for purpose, err in res["errors"]:
                    _log(db, purpose, material.user_id, None, err)
                if res["solve"]:
                    _log(db, "answer_key", material.user_id, res["solve"].usage)
                if res["check"]:
                    _log(db, "answer_verify", material.user_id, res["check"].usage)
                solved = {it.idx: it for it in (res["solve"].data.items if res["solve"] else [])}
                checked = {it.idx: it for it in (res["check"].data.items if res["check"] else [])}
                for i, p in enumerate(chunk, 1):
                    _apply(p, rows[p.id], solved.get(i), checked.get(i))
                    solved_any = solved_any or i in solved
                material.answer_key_done += len(chunk)
                db.commit()
        material.answer_key_status = "done" if solved_any else "failed"
        material.answer_key_error = None if solved_any else "정답지를 만들지 못했어요. 잠시 후 다시 시도해 주세요"
        material.answer_key_at = datetime.now(timezone.utc)
        _notify(db, material, rows)
        db.commit()


def _apply(p: m.Problem, row: m.ProblemAnswer, solved: Solved | None, checked: Checked | None) -> None:
    if solved is None:
        if not row.ai_answer:
            row.status = "failed"
        refresh(p, row)
        return
    row.ai_answer = normalize(p, solved.answer)
    row.ai_solution = solved.solution.strip()[:6000] or None
    row.check_answer = normalize(p, checked.answer) if checked else None
    refresh(p, row)


def _notify(db: Session, material: m.Material, rows: dict[str, m.ProblemAnswer]) -> None:
    if material.answer_key_status != "done":
        notifications.notify(db, material.user_id, "material", f"정답지 만들기 실패 · {material.filename[:60]}",
                             body=material.answer_key_error, link=f"#/project/{material.project_id}")
        return
    need = sum(r.status in ("conflict", "uncertain") for r in rows.values())
    notifications.notify(db, material.user_id, "material", f"정답지 완성 · {material.filename[:60]}",
                         body=f"{len(rows)}문항의 정답과 해설을 만들었어요." + (f" {need}문항은 한 번 더 확인해 주세요." if need else ""),
                         link=f"#/answer-key/{material.id}")


# ---------- 정답 파일 ↔ 문제지 1:1 매칭 ----------
def map_answer_sheet(db: Session, sheet: m.Material, target: m.Material, entries: list[tuple[int | None, str, str | None]]) -> dict:
    """정답 파일에서 읽은 (번호, 정답, 해설) 을 문제지의 문항과 번호로 1:1 매칭한다.
    문제지에 번호가 없으면 순서대로 맞춘다. 결과 요약을 돌려준다."""
    problems = problems_of(db, target)
    numbered = all(number_of(p) is not None for p in problems)
    by_number = {number_of(p): p for p in problems} if numbered else {i: p for i, p in enumerate(problems, 1)}
    seen, extra = set(), []
    for k, (num, answer, explanation) in enumerate(entries, 1):
        key = num if numbered and num is not None else k
        p = by_number.get(key)
        if p is None or key in seen:
            if num is not None:
                extra.append(num)
            continue
        ans = normalize(p, answer)
        if not ans:
            continue
        seen.add(key)
        row = row_of(db, p)
        row.sheet_answer, row.sheet_material_id = ans, sheet.id
        row.sheet_explanation = (explanation or "").strip()[:4000] or None
        refresh(p, row)
    missing = sorted(k for k in by_number if k not in seen)
    return {"matched": len(seen), "total": len(problems), "missing": missing[:200], "extra": sorted(set(extra))[:200],
            "entries": [[n, a, (e or "")[:2000]] for n, a, e in entries][:500]}


def remap(db: Session, target: m.Material) -> dict | None:
    """문항 번호를 고친 뒤 연결된 정답 파일을 다시 맞춘다 (정답 파일에서 읽어 둔 항목으로, AI 를 다시 부르지 않음)."""
    sheet = db.scalar(select(m.Material).where(m.Material.answer_for_id == target.id))
    entries = (sheet.answer_map or {}).get("entries") if sheet else None
    if not sheet or entries is None:
        return None
    unmap_answer_sheet(db, sheet)
    db.flush()
    summary = map_answer_sheet(db, sheet, target, [tuple(e) for e in entries])
    sheet.answer_map, sheet.problem_count = summary, summary["matched"]
    return summary


def unmap_answer_sheet(db: Session, sheet: m.Material) -> None:
    """정답 파일을 지우면 그 파일에서 온 정답만 거두고 문제지에 인쇄돼 있던 정답으로 돌아간다 (AI 풀이는 남는다)."""
    for row in db.scalars(select(m.ProblemAnswer).where(m.ProblemAnswer.sheet_material_id == sheet.id)):
        row.sheet_answer, row.sheet_explanation, row.sheet_material_id = row.printed_answer or "", None, None
        p = db.get(m.Problem, row.problem_id)
        if p is not None:
            refresh(p, row)


# ---------- 화면 ----------
def view(db: Session, material: m.Material) -> dict:
    """정답지 화면에 보낼 내용."""
    items, counts = [], {"manual": 0, "sheet": 0, "confirmed": 0, "verified": 0, "conflict": 0, "uncertain": 0, "failed": 0, "none": 0}
    for p in problems_of(db, material):
        row = db.get(m.ProblemAnswer, p.id)
        st = (row.status if row else None) or "none"
        counts[st] = counts.get(st, 0) + 1
        items.append({
            "id": p.id, "number": number_of(p), "stem": p.stem, "choices": p.choices,
            "answer": p.answer or (row.ai_answer if row else "") or "",
            "sheet_answer": row.sheet_answer if row else "", "sheet_explanation": row.sheet_explanation if row else None,
            "from_answer_file": bool(row and row.sheet_material_id),
            "ai_answer": row.ai_answer if row else None, "status": st,
            "needs_figure": bool((p.generation_meta or {}).get("needs_figure")), "page": (p.generation_meta or {}).get("page"),
            "manual": bool(row and row.manual_answer),
            "solution": row.ai_solution if row else None, "concept_ids": p.concept_ids,
        })
    sheet = db.scalar(select(m.Material).where(m.Material.answer_for_id == material.id))
    return {"material": {"id": str(material.id), "filename": material.filename, "kind": material.kind,
                         "project_id": str(material.project_id), "status": material.status, "problem_count": material.problem_count,
                         "answer_key_status": material.answer_key_status, "answer_key_error": material.answer_key_error,
                         "answer_key_done": material.answer_key_done,
                         "answer_key_at": material.answer_key_at.isoformat() if material.answer_key_at else None},
            "answer_file": {"id": str(sheet.id), "filename": sheet.filename, "status": sheet.status, "map": sheet.answer_map} if sheet else None,
            "counts": counts, "items": items}
