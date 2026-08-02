"""알림·웹푸시 라우터 — 개인 알림함 + 구독 관리 (CLAUDE.md §6.10, §9.4).

알림은 본인 것만 조회/처리. 구독은 endpoint 기준 upsert(재구독 시 소유자 갱신).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.staff.employee import Employee
from app.models.chat.notification import Notification, PushSubscription
from app.schemas.chat.notification import NotificationOut, PushSubscribeIn, VapidPublicKeyOut

router = APIRouter(tags=["notifications"], dependencies=[Depends(get_current_user)])


# ---------- 알림함 ----------
@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    read: bool | None = Query(None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    stmt = select(Notification).where(Notification.employee_id == current.id)
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
