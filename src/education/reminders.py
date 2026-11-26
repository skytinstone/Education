"""하루 한 번 학습 알림 만들기 (서버 cron 이 부른다, docs/DEPLOY.md 11번).

    python -m education.reminders            # 아침: 복습·시험 D-day·암기 카드
    python -m education.reminders --evening  # 저녁: 연속 학습이 끊기기 전에
"""

import argparse

from education.db.session import SessionLocal
from education.ai import rag
from education.services import item_stats, reminders


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evening", action="store_true", help="저녁 알림 (연속 학습)")
    args = parser.parse_args()
    with SessionLocal() as db:
        sent = reminders.run(db, evening=args.evening)
        if not args.evening:  # 아침마다 문제 성적표도 새로 매긴다 (문제 생성이 참고)
            stats = item_stats.refresh(db)
            db.commit()
            print(f"문제 성적표 {stats['problems']}문제")
            print(f"RAG 임베딩 {rag.backfill(db)}문제")  # 새 문제를 검색에 잡히게
            db.commit()
    print(" · ".join(f"{k} {v}명" for k, v in sent.items()) or "보낼 알림 없음")


if __name__ == "__main__":
    main()
