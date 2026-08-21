"""알림·웹푸시 라우터 — 개인 알림함 + 구독 관리 (CLAUDE.md §6.10, §9.4).

알림은 본인 것만 조회/처리. 구독은 endpoint 기준 upsert(재구독 시 소유자 갱신).
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.staff.employee import Employee
from app.models.chat.device_token import DeviceToken
from app.models.chat.notification import Notification, PushSubscription
from app.schemas.chat.notification import (
    DeviceTokenIn,
    NotificationOut,
    PushSubscribeIn,
    VapidPublicKeyOut,
)

router = APIRouter(tags=["notifications"], dependencies=[Depends(get_current_user)])


# ---------- 알림함 ----------
#: 알림함이 거슬러 올라가는 날 수 — **기본 7일** (2026-08-21 대표 결정)
#:
#: 안 자르면 그 사람 알림이 **한 번에 전부** 온다. 개발 DB 가 한 달 만에
#: 1,242건이었다 — 하루 40건꼴이라 반년이면 7천 건을 매번 받아서 화면에
#: 안 보일 줄까지 그린다.
#:
#: **행을 지우지는 않는다.** 조회에서만 뺀다 — 지우면 되짚을 길이 없다.
NOTIFICATION_DAYS = 7


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    read: bool | None = Query(None),
    days: int = Query(NOTIFICATION_DAYS, ge=1, le=90, description="며칠치를 볼지"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    """내 알림함 — **최근 [days] 일치만** 준다 (기본 7일).

    앱의 안 읽음 배지도 이 목록을 세므로, 여기서 자르면 **7일보다 오래된
    안 읽은 알림은 배지에서도 빠진다.** 그게 의도다 — 화면에 안 보이는
    것이 배지에만 잡히면 눌러도 찾을 수가 없다.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(Notification).where(
        Notification.employee_id == current.id,
        Notification.created_at >= since,
    )
    if read is not None:
        stmt = stmt.where(Notification.read == read)
    result = await db.execute(stmt.order_by(Notification.created_at.desc()))
    return list(result.scalars().all())


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.employee_id != current.id:
        raise HTTPException(404, detail={"code": "NOTIFICATION_NOT_FOUND", "message": "알림을 찾을 수 없습니다"})
    notification.read = True
    await db.commit()
    await db.refresh(notification)
    return notification


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.employee_id == current.id, Notification.read.is_(False))
        .values(read=True)
    )
    await db.commit()
    return None


# ---------- 웹푸시 구독 ----------
@router.get("/push/vapid-public-key", response_model=VapidPublicKeyOut)
async def vapid_public_key() -> VapidPublicKeyOut:
    return VapidPublicKeyOut(public_key=settings.vapid_public_key)


@router.post("/push/subscribe", status_code=204)
async def subscribe(
    payload: PushSubscribeIn,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if existing is not None:  # 같은 브라우저 재구독 — 소유자/키 갱신
        existing.employee_id = current.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
    else:
        db.add(
            PushSubscription(
                employee_id=current.id,
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
            )
        )
    await db.commit()
    return None


@router.delete("/push/subscribe", status_code=204)
async def unsubscribe(
    payload: PushSubscribeIn,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    sub = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if sub is not None:
        await db.delete(sub)
        await db.commit()
    return None


# ---------- 앱 푸시(APNs) 기기 토큰 ----------
#
# 웹푸시 구독(`/push/subscribe`)과 **따로 둔다** — 저쪽은 브라우저 endpoint 고
# 이건 애플이 준 기기 토큰이다. 한 사람이 폰·PC 를 같이 쓰면 둘 다 쌓인다.
@router.post("/push/devices", status_code=204)
async def register_device(
    payload: DeviceTokenIn,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """기기 토큰 등록 — 앱이 켤 때마다 부른다 (같은 토큰이면 갱신만 된다).

    **같은 폰에 다른 사람이 로그인하면 주인이 바뀐다.** 안 바꾸면 그 폰으로
    앞사람 알림이 계속 간다.
    """
    device = await db.scalar(select(DeviceToken).where(DeviceToken.token == payload.token))
    if device is None:
        device = DeviceToken(token=payload.token)
        db.add(device)
    device.employee_id = current.id
    device.platform = payload.platform
    device.sandbox = payload.sandbox
    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return None


@router.delete("/push/devices/{token}", status_code=204)
async def unregister_device(
    token: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """로그아웃할 때 지운다 — 안 지우면 이 폰으로 앞사람 알림이 계속 간다.

    **본인 것만 지운다.** 남의 토큰을 지워 알림을 끊을 수 있으면 안 된다.
    """
    device = await db.scalar(
        select(DeviceToken).where(
            DeviceToken.token == token, DeviceToken.employee_id == current.id
        )
    )
    if device is not None:
        await db.delete(device)
        await db.commit()
    return None
