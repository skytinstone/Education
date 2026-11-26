"""하네스 평가 실행.

    python -m education.harness.evals                     # 실제 AI 로 평가 (비용이 들어요) → eval_runs 에 저장
    python -m education.harness.evals --record out.json   # 녹화한 카세트도 파일로 (CI 재생용)
    python -m education.harness.evals --replay cassette.json   # 녹화된 응답으로 다시 계산 (AI 를 부르지 않음)
"""

import argparse
import json
import sys
from pathlib import Path

from education.db.session import SessionLocal
from education.harness.evals import runner
from education.services.llm import get_llm


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--replay", type=Path)
    p.add_argument("--record", type=Path)
    p.add_argument("--suite", action="append", choices=["verify", "retrieval", "generate"])
    a = p.parse_args()
    suites = tuple(a.suite or ["verify", "retrieval"])
    with SessionLocal() as db:
        if a.replay:
            run, tape = runner.run(db, mode="replay", cassette=json.loads(a.replay.read_text(encoding="utf-8")), suites=suites)
        else:
            llm = get_llm()
            if llm is None:
                sys.exit("OPENAI_API_KEY 가 없어요")
            run, tape = runner.run(db, llm=llm, mode="live", suites=suites)
        db.commit()
        if a.record:
            a.record.write_text(json.dumps(tape, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"run": str(run.id), "harness_version": run.harness_version, "metrics": run.metrics}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
