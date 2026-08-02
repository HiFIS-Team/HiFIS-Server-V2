"""일정(Event) 리마인더 — 매일 09:00 KST 1회 (CLAUDE.md §9.5).

일정 시작 기준 D-7 / D-3 / 전날(D-1) / 당일(D-0)에 소유자에게 알림(+웹푸시).
앱 내 알림으로 남긴다(하루 최대 1건이라 폭주 없음).
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.models.board.event import Event
from app.services import notification_texts as ntext
from app.services.notifications import notify

REMIND_DAYS = {7, 3, 1, 0}


async def event_reminders(now: datetime | None = None) -> None:
    now_utc = now or datetime.now(timezone.utc)
    today = now_utc.astimezone(KST).date()
    horizon_start = datetime.combine(today, time.min, tzinfo=KST)
    horizon_end = horizon_start + timedelta(days=8)  # 오늘 ~ +7일 시작분만
    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(Event).where(
                    Event.start_at >= horizon_start, Event.start_at < horizon_end
                )
            )
        ).scalars().all()
        for e in events:
            days = (e.start_at.astimezone(KST).date() - today).days
            if days not in REMIND_DAYS:
                continue
            label = "오늘" if days == 0 else f"D-{days}"
            await notify(
                db,
                employee_id=e.owner_id,
                **ntext.event_reminder(label, e.title, e.start_at.astimezone(KST)),
            )
        await db.commit()
