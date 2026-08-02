"""알림 서비스 — 앱 내 알림 저장 + 웹푸시 발송 (CLAUDE.md §6.10, §9.4).

- notify(): Notification 원장 1건 추가(+구독 있으면 best-effort 웹푸시). commit 은 호출자.
- 웹푸시는 VAPID 미설정/pywebpush 미설치면 조용히 스킵 — 앱 내 알림은 항상 남는다.
- 만료 구독(404/410)은 같은 세션에서 삭제 예약(호출자 commit 시 정리).
"""

import json
import logging

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat.notification import Notification, PushSubscription

logger = logging.getLogger(__name__)

try:  # pywebpush 는 선택 의존 — 없으면 앱 내 알림만 동작
    from pywebpush import WebPushException, webpush

    _PUSH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PUSH_AVAILABLE = False


def _push_enabled() -> bool:
    return _PUSH_AVAILABLE and bool(settings.vapid_private_key)


async def notify(
    db: AsyncSession,
    *,
    employee_id: str,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    """알림 1건 적립 + (가능하면) 웹푸시. commit 은 호출자."""
    notification = Notification(
        employee_id=employee_id, type=type, title=title, body=body, link=link
    )
    db.add(notification)

    if _push_enabled():
        await _push(db, employee_id, {"type": type, "title": title, "body": body, "link": link})
    return notification


async def send_push(
    db: AsyncSession,
    *,
    employee_id: str,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    """웹푸시만 발송(앱 내 알림함엔 안 남김). 채팅·반복 리마인더처럼 알림함이 넘칠 이벤트용.

    만료 구독 정리(_push)가 db.delete 를 예약할 수 있어 commit 은 호출자 책임.
    """
    if _push_enabled():
        await _push(db, employee_id, {"type": type, "title": title, "body": body, "link": link})


async def _push(db: AsyncSession, employee_id: str, payload: dict) -> None:
    subs = (
        await db.scalars(
            select(PushSubscription).where(PushSubscription.employee_id == employee_id)
        )
    ).all()
    data = json.dumps(payload, ensure_ascii=False)
    for sub in subs:
        try:
            await run_in_threadpool(_send_one, sub, data)
        except WebPushException as exc:  # 만료·무효 구독 정리
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                await db.delete(sub)
            else:
                logger.warning("webpush 실패(%s): %s", status, exc)
        except Exception as exc:  # 네트워크 등 — 앱 내 알림은 유지
            logger.warning("webpush 예외: %s", exc)


def _send_one(sub: PushSubscription, data: str) -> None:
    webpush(
        subscription_info={
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        },
        data=data,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
    )
