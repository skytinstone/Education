"""평가 하네스 — 골든셋으로 지금 하네스의 품질을 숫자로 잰다.

두 묶음 (suite)
- verify   : 좋은 문제는 통과시키고 망가진 문제(정답 번호 오류 · 복수 정답 · 조건 누락 · 맞는 보기 없음)는 거르는가.
             실제 문제 생성과 같은 검사 층을 그대로 쓴다 — 검증 AI(독립 재풀이) → 검산 에이전트(SymPy 도구, 수학·물리)
- retrieval: 학생 요청 같은 문장으로 RAG 검색했을 때 위 3개 안에 기대 개념의 문제가 나오는가

지표
- detection_rate        망가진 문제를 거른 비율 (재현율) ↑
- false_reject_rate     좋은 문제를 잘못 버린 비율 ↓
- verifier_detection    검증 AI 혼자 거른 비율 / math_check_added  검산 에이전트가 '추가로' 거른 비율 → Tool Calling 의 기여
- math_check_accuracy   검산 에이전트가 돈 경우 판단이 맞은 비율
- by_defect             결함 종류별 탐지율
- recall_at_3 · mrr     RAG 검색 품질
- cost_usd · avg_ms     비용 · 시간

모드
- live   : 실제 AI 를 부르고, 응답을 카세트(cassette)에 녹화한다
- replay : 녹화된 응답으로 같은 판정·지표 계산을 다시 한다 — CI 에서 돈 들이지 않고 판정 로직·지표 계산의 회귀를 막는다
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from education.ai import math_check, rag
from education.db import models as m
from education.harness import prompts
from education.services import generator
from education.services.generator import FORMATS, VERIFIER_INSTRUCTIONS, GeneratedProblem, Verdict
from education.services.llm import LLM, LLMError, Usage

GOLDEN = Path(__file__).parent / "golden"
TOOL_DOMAINS = {"math", "physics"}


def load(suite: str) -> list[dict]:
    return yaml.safe_load((GOLDEN / f"{suite}.yaml").read_text(encoding="utf-8"))["cases"]


def _usage_dict(u: Usage | None) -> dict | None:
    return None if u is None else {"model": u.model, "in": u.input_tokens, "out": u.output_tokens, "cost": u.cost_usd}


# ---------- verify ----------
def _verify_case(case: dict, llm: LLM | None, rec: dict | None, tool_check: bool) -> dict:
    """한 문제를 실제 생성 파이프라인의 검사 층에 통과시킨다. rec 가 있으면 녹화된 응답을 쓴다 (replay)."""
    from education.config import get_settings
    s = get_settings()
    _, _, _, question_of, agrees = FORMATS["multiple_choice"]
    problem = GeneratedProblem(stem=case["stem"], choices=case["choices"], answer=case["answer"], solution="-", traps=[])
    question = question_of(problem)
    started = time.monotonic()
    out: dict = {"id": case["id"], "label": case["label"], "defect": case.get("defect"), "domain": case.get("domain")}
    cost = 0.0

    if rec is not None:
        verdict = Verdict(**rec["verifier"]["verdict"])
        out["verifier"] = rec["verifier"]
    else:
        res = llm.structured(model=s.openai_model_verify, effort=s.openai_effort_verify, instructions=VERIFIER_INSTRUCTIONS,
                             prompt=question, schema=Verdict)
        verdict = res.data
        out["verifier"] = {"verdict": verdict.model_dump(), "usage": _usage_dict(res.usage)}
    cost += (out["verifier"].get("usage") or {}).get("cost") or 0
    verifier_reject = (not verdict.well_posed) or (not agrees(problem, verdict))

    math_reject = False
    ran_math = (not verifier_reject) and tool_check and case.get("domain") in TOOL_DOMAINS
    if ran_math:
        if rec is not None and rec.get("math") is not None:
            out["math"] = rec["math"]
        elif rec is not None:
            ran_math = False  # 녹화 당시 검산을 안 했음
        else:
            try:
                mc, u, messages = math_check.check(question, generator._answer_for_check(problem))
                out["math"] = {**mc.model_dump(), "tools": math_check.tool_calls(messages), "usage": _usage_dict(u)}
            except LLMError as e:
                out["math"] = {"error": str(e)[:300]}
        if ran_math and "error" not in out.get("math", {}):
            math_reject = out["math"]["checkable"] and not out["math"]["agrees"]
            cost += (out["math"].get("usage") or {}).get("cost") or 0

    out["decision"] = "reject" if (verifier_reject or math_reject) else "pass"
    out["caught_by"] = "verifier" if verifier_reject else "math_check" if math_reject else None
    out["cost_usd"] = round(cost, 6)
    out["ms"] = rec.get("ms", 0) if rec is not None else int((time.monotonic() - started) * 1000)
    return out


def verify_metrics(results: list[dict]) -> dict:
    good = [r for r in results if r["label"] == "good"]
    bad = [r for r in results if r["label"] == "bad"]
    rate = lambda xs, f: round(sum(1 for x in xs if f(x)) / len(xs), 4) if xs else None  # noqa: E731
    by_defect = {}
    for d in sorted({r["defect"] for r in bad}):
        rows = [r for r in bad if r["defect"] == d]
        by_defect[d] = {"cases": len(rows), "detected": rate(rows, lambda r: r["decision"] == "reject")}
    ran = [r for r in results if r.get("math") and "error" not in r["math"] and r["math"].get("checkable")]
    should_fail = {"wrong_key", "no_correct_choice"}
    math_ok = lambda r: r["math"]["agrees"] if r["label"] == "good" else (not r["math"]["agrees"]) if r["defect"] in should_fail else True  # noqa: E731
    return {
        "cases": len(results), "good": len(good), "bad": len(bad),
        "detection_rate": rate(bad, lambda r: r["decision"] == "reject"),
        "false_reject_rate": rate(good, lambda r: r["decision"] == "reject"),
        "verifier_detection": rate(bad, lambda r: r["caught_by"] == "verifier"),
        "math_check_added": rate(bad, lambda r: r["caught_by"] == "math_check"),
        "math_check_runs": len(ran),
        "math_check_accuracy": rate(ran, math_ok),
        "by_defect": by_defect,
        "cost_usd": round(sum(r["cost_usd"] for r in results), 4),
        "avg_ms": int(sum(r["ms"] for r in results) / len(results)) if results else 0,
    }


# ---------- retrieval ----------
def _retrieval_case(db: Session, case: dict, rec: list | None) -> dict:
    if rec is None:
        hits = rag.search(db, None, case["query"], k=3)
        top = [{"problem_id": h.problem.id, "concepts": h.problem.concept_ids, "similarity": round(h.similarity, 4)} for h in hits]
    else:
        top = rec
    rank = next((i + 1 for i, h in enumerate(top) if case["concept_id"] in h["concepts"]), None)
    return {"id": case["id"], "query": case["query"], "expected": case["concept_id"], "top": top, "rank": rank}


def retrieval_metrics(results: list[dict]) -> dict:
    n = len(results)
    return {"cases": n,
            "recall_at_3": round(sum(1 for r in results if r["rank"]) / n, 4) if n else None,
            "mrr": round(sum(1 / r["rank"] for r in results if r["rank"]) / n, 4) if n else None}


# ---------- 실행 ----------
def run(db: Session, *, llm: LLM | None = None, mode: str = "live", cassette: dict | None = None,
        suites: tuple[str, ...] = ("verify", "retrieval"), tool_check: bool = True, workers: int = 6,
        eval_run: m.EvalRun | None = None) -> tuple[m.EvalRun, dict]:
    """평가 한 번. live 면 녹화한 카세트도 돌려준다. 결과는 eval_runs 에 저장."""
    if mode == "replay" and cassette is None:
        raise ValueError("replay 에는 카세트가 필요해요")
    if mode == "live" and llm is None and "verify" in suites:
        raise ValueError("live 평가에는 AI 가 필요해요")
    started = time.monotonic()
    run_row = eval_run or m.EvalRun(harness_version=prompts.harness_version(), mode=mode, status="running",
                                    suites=list(suites), prompt_versions=prompts.versions(), models=prompts.models())
    if eval_run is None:
        db.add(run_row)
        db.flush()
    metrics: dict = {}
    cases: dict = {}
    tape: dict = {"harness_version": prompts.harness_version(), "verify": {}, "retrieval": {}}

    if "verify" in suites:
        golden = load("verify")
        recs = (cassette or {}).get("verify", {})
        if mode == "replay":
            golden = [c for c in golden if c["id"] in recs]
        with ThreadPoolExecutor(max_workers=workers if mode == "live" else 1) as pool:
            results = list(pool.map(lambda c: _verify_case(c, llm, recs.get(c["id"]) if mode == "replay" else None, tool_check), golden))
        for r in results:
            tape["verify"][r["id"]] = {k: r[k] for k in ("verifier", "ms") if k in r} | ({"math": r["math"]} if "math" in r else {})
        metrics["verify"] = verify_metrics(results)
        cases["verify"] = results

    if "retrieval" in suites:
        golden = load("retrieval")
        recs = (cassette or {}).get("retrieval", {})
        if mode == "replay":
            golden = [c for c in golden if c["id"] in recs]
        results = [_retrieval_case(db, c, recs.get(c["id"]) if mode == "replay" else None) for c in golden]
        for r in results:
            tape["retrieval"][r["id"]] = r["top"]
        metrics["retrieval"] = retrieval_metrics(results)
        cases["retrieval"] = results

    tape["metrics"] = metrics
    run_row.metrics, run_row.cases, run_row.status = metrics, cases, "done"
    run_row.cost_usd = metrics.get("verify", {}).get("cost_usd") if mode == "live" else 0
    run_row.latency_ms = int((time.monotonic() - started) * 1000)
    run_row.finished_at = func.now()
    db.flush()
    return run_row, tape
