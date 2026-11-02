"""운영자에게 보내는 메일 (새 피드백 알림 등).

SMTP 설정(.env 의 SMTP_*)이 없으면 아무것도 하지 않는다. 응답을 늦추지 않도록 별도 스레드에서 보낸다.
Gmail: smtp.gmail.com · 587 · SMTP_USER=보내는 Gmail 주소 · SMTP_PASSWORD=앱 비밀번호(2단계 인증 후 발급)
"""

from __future__ import annotations

import logging
import smtplib
import threading
from email.message import EmailMessage

from education.config import get_settings

log = logging.getLogger(__name__)


def configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_user and s.smtp_password)


def _send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_user, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        log.warning("메일 발송 실패 (%s): %s", subject, e)


def send_later(to: str | None, subject: str, body: str) -> None:
    if not to or not configured():
        return
    threading.Thread(target=_send, args=(to, subject, body), daemon=True).start()
