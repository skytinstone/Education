"""하루 한 번 학습 알림 만들기 (서버 cron 이 부른다, docs/DEPLOY.md 11번).

    python -m education.reminders            # 아침: 복습·시험 D-day·암기 카드
    python -m education.reminders --evening  # 저녁: 연속 학습이 끊기기 전에
"""

import argparse

from education.db.session import SessionLocal
from education.services import reminders


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evening", action="store_true", help="저녁 알림 (연속 학습)")
    args = parser.parse_args()
    with SessionLocal() as db:
        sent = reminders.run(db, evening=args.evening)
    print(" · ".join(f"{k} {v}명" for k, v in sent.items()) or "보낼 알림 없음")


if __name__ == "__main__":
    main()
