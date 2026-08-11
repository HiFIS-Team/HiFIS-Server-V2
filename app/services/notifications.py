"""알림 서비스 — 앱 내 알림 저장 + 푸시 발송 (CLAUDE.md §6.10, §9.4).

- notify(): Notification 원장 1건 추가(+ best-effort 푸시). commit 은 호출자.
- 푸시는 **두 갈래를 다 태운다** — 브라우저는 웹푸시(VAPID), 앱은 APNs.
  둘 중 설정 안 된 쪽은 조용히 스킵한다. 앱 내 알림은 언제나 남는다.
- 죽은 구독·토큰(404/410/BadDeviceToken)은 같은 세션에서 삭제 예약(호출자 commit 시 정리).
"""

import json
import logging

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums import EmployeeStatus, Role
from app.models.chat.device_token import DeviceToken
from app.models.chat.notification import Notification, PushSubscription
from app.models.staff.employee import Employee
from app.services import apns

logger = logging.getLogger(__name__)

try:  # pywebpush 는 선택 의존 — 없으면 앱 내 알림만 동작
    from pywebpush import WebPushException, webpush

    _PUSH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PUSH_AVAILABLE = False


def _push_enabled() -> bool:
    return _PUSH_AVAILABLE and bool(settings.vapid_private_key)


async def boss_ids(db: AsyncSession, *, exclude: str | None = None) -> list[str]:
    """전사 상황 알림을 받는 사람 — **MASTER · ADMIN** (2026-08-11 대표 결정).

    출퇴근·결근·프로젝트·회의록·인사처럼 **남의 일**을 알리는 자리에서 쓴다.
    본인 일을 본인에게 알리는 것들(결재·급여·휴가 결과)은 여기를 안 쓴다.

    [exclude] 는 그 일을 **직접 한 사람**이다. 대표가 프로젝트를 만들고 자기가
    "새 프로젝트가 만들어졌어요" 를 받으면 이상하다.
    """
    rows = await db.scalars(
        select(Employee.id).where(
            Employee.role.in_([Role.MASTER, Role.ADMIN]),
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.deleted_at.is_(None),
        )
    )
    return [eid for eid in rows if eid != exclude]


async def notify_bosses(db: AsyncSession, *, exclude: str | None = None, **text) -> None:
    """[boss_ids] 전원에게 같은 알림 — 부르는 쪽이 매번 루프를 돌지 않게."""
    for eid in await boss_ids(db, exclude=exclude):
        await notify(db, employee_id=eid, **text)


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

    await _fanout(db, employee_id, {"type": type, "title": title, "body": body, "link": link})
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
    await _fanout(db, employee_id, {"type": type, "title": title, "body": body, "link": link})


async def _fanout(db: AsyncSession, employee_id: str, payload: dict) -> None:
    """웹푸시와 앱 푸시를 둘 다 태운다 — 한쪽이 실패해도 다른 쪽은 간다"""
    if _push_enabled():
        await _push(db, employee_id, payload)
    if apns.enabled():
        await _push_apns(db, employee_id, payload)


async def _push_apns(db: AsyncSession, employee_id: str, payload: dict) -> None:
    devices = (
        await db.scalars(select(DeviceToken).where(DeviceToken.employee_id == employee_id))
    ).all()
    for device in devices:
        dead = await apns.send(
            token=device.token,
            sandbox=device.sandbox,
            title=payload["title"],
            body=payload.get("body"),
            link=payload.get("link"),
            type=payload["type"],
        )
        # 앱을 지웠거나 토큰이 무효다 — 안 지우면 계속 보내다 애플이 막는다
        if dead:
            logger.info("apns 토큰 정리(%s): %s", dead, device.token[:12])
            await db.delete(device)


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
