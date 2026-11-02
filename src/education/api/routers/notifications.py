"""내 알림 — 목록과 읽음 처리."""

from fastapi import APIRouter, Response, status

from education.api.deps import DB, CurrentUser
from education.api.dto import NotificationList, NotificationOut, NotificationRead
from education.services import notifications

router = APIRouter(tags=["알림"])


@router.get("/notifications")
def list_notifications(user: CurrentUser, db: DB) -> NotificationList:
    """최근 30개와 안 읽은 개수."""
    return NotificationList(unread=notifications.unread_count(db, user.id),
                            items=[NotificationOut.model_validate(n) for n in notifications.recent(db, user.id)])


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
def read_notifications(body: NotificationRead, user: CurrentUser, db: DB) -> Response:
    """ids 를 주면 그 알림만, 비우면 모두 읽음 (남의 알림 id 는 무시된다)."""
    notifications.mark_read(db, user.id, body.ids)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
