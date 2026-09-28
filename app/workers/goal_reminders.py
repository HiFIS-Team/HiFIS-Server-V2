"""이달의 목표 재촉 — **매달 첫 번째 월요일 09:00 KST** (2026-09-28 대표 요청).

아직 안 적은 MANAGER·MEMBER 에게만 보낸다. 한 달에 한 번이라 알림함에도 남긴다.
그 뒤로는 앱을 열 때 모달이 짚는다 (`GET /goals/me` 의 `due`).
"""

import logging
from datetime import datetime

from app.db.session import SessionLocal
from app.services import notification_texts as ntext
from app.services.monthly_goals import first_monday, missing_now, today_kst
from app.services.notifications import notify

logger = logging.getLogger(__name__)


async def goal_reminders(now: datetime | None = None) -> None:
    """[now] 는 테스트에서 시계를 옮기려고 받는다."""
    today = today_kst(now)
    if today != first_monday(today):
        return
    async with SessionLocal() as db:
        people = await missing_now(db, today)
        for person in people:
            await notify(db, employee_id=person.id, **ntext.goal_reminder(today.month))
        await db.commit()
        logger.info("goal_reminders: %d명", len(people))
