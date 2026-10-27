"""AI 로 문제를 만들어 문제 은행에 쌓는다 (실제 API 호출 — 비용 발생).

    uv run python -m education.generate --concept math.calculus.int_methods.substitution_parts --difficulty 3 --count 2
    uv run python -m education.generate --text "로그의 성질 쉬운 문제 2개"
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from education.db import models as m
from education.db.session import SessionLocal
from education.services import generator
from education.services.llm import get_llm


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--concept", help="개념 id")
    parser.add_argument("--text", help="자연어 요청 (개념·난이도·문항 수를 읽음)")
    parser.add_argument("--difficulty", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--count", type=int, default=1, choices=range(1, 6))
    args = parser.parse_args()

    llm = get_llm()
    if llm is None:
        sys.exit(".env 에 OPENAI_API_KEY 가 없어요")

    with SessionLocal() as db:
        if args.text:
            plan = generator.plan_request(db, args.text, max_count=5)
            if plan is None:
                sys.exit("요청에서 개념을 찾지 못했어요")
            concept_id, difficulty, count = plan.concept_id, plan.difficulty, plan.count
        elif args.concept:
            concept_id, difficulty, count = args.concept, args.difficulty, args.count
        else:
            sys.exit("--concept 또는 --text 를 주세요")

        print(f"생성 중: {db.get(m.Concept, concept_id).name} · 난이도 {difficulty} · {count}문제 …", flush=True)
        report = generator.generate_problems(db, llm, concept_id=concept_id, difficulty=difficulty, count=count)

        for pid in report.accepted + report.rejected:
            p = db.get(m.Problem, pid)
            meta = p.generation_meta
            mark = "✅ 통과" if pid in report.accepted else f"❌ 탈락 ({meta['reject_reason']})"
            print(f"\n{mark}  [{pid}]\n{p.stem}")
            for i, c in enumerate(p.choices, 1):
                print(f"  {i}) {c}{'  ← 정답' if str(i) == p.answer else ''}")
            print(f"해설: {p.solution}\n검증자 답: {meta['verifier_answer']}  지적: {meta['verifier_issues'] or '없음'}")
        # 문제가 저장되지도 못한 실패 (API 오류, 형식 오류 반복 등)
        for reason in report.reasons[len(report.rejected):]:
            print(f"\n⚠️ {reason}")

        calls = db.scalars(select(m.LLMCall).order_by(m.LLMCall.created_at.desc()).limit(count * 6)).all()
        secs = sum(c.latency_ms for c in calls) / 1000
        print(f"\n{report.calls_summary} · AI 호출 {len(calls)}번 (누적 {secs:.0f}초, 동시 실행이라 실제 대기는 더 짧음)")


if __name__ == "__main__":
    main()
