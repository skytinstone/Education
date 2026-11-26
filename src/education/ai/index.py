"""임베딩이 없는 문제를 채운다 (RAG 색인).

    python -m education.ai.index            # 최대 2000문제
    python -m education.ai.index --limit 500
"""

import argparse

from education.ai import rag
from education.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()
    with SessionLocal() as db:
        n = rag.backfill(db, limit=args.limit)
        db.commit()
        print(f"임베딩 {n}문제 · 전체 {rag.coverage(db)}")


if __name__ == "__main__":
    main()
