"""오래 멈춘 백그라운드 작업 정리.

업로드 분석·정답지는 서버 안에서 백그라운드로 돈다. 그 사이 배포·재시작되면 작업이 사라져 '진행 중'에서 멈추므로,
화면이 목록·정답지를 열 때 너무 오래된 '진행 중'을 실패로 바꿔 다시 시도할 수 있게 한다.
(서버 여러 개가 동시에 돌아도 아직 살아 있는 작업은 건드리지 않도록 시간 기준으로만 판단한다)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from education.db import models as m

EXTRACT_LIMIT = timedelta(minutes=15)
ANSWER_KEY_LIMIT = timedelta(minutes=30)
RESTARTED = "작업이 중간에 멈췄어요 (서버가 다시 시작됐을 수 있어요). 다시 시도해 주세요"


def heal(db: Session, material: m.Material) -> bool:
    """멈춘 작업이면 실패로 바꾸고 True."""
    now, changed = datetime.now(timezone.utc), False
    if material.status in ("uploaded", "extracting") and now - material.created_at > EXTRACT_LIMIT:
        material.status, material.error = "failed", RESTARTED
        changed = True
    started = material.answer_key_started_at or material.created_at
    if material.answer_key_status == "running" and now - started > ANSWER_KEY_LIMIT:
        material.answer_key_status, material.answer_key_error = "failed", RESTARTED
        changed = True
    return changed
