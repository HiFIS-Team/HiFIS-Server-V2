"""생일 알림 — 매일 09:00 KST (2026-09-27 대표 요청).

| 언제 | 누구에게 | 무엇 |
|---|---|---|
| 전날 | 생일자 **말고** 전원 | `내일 00님 생일이에요!` |
| 당일 | 생일자 말고 전원 | `오늘 00님 생일이에요! 축하 메시지를 보내보세요!` |
| 당일 | 생일자 | `생일 축하해요!` |

**권한을 안 가린다** — MASTER·ADMIN·MANAGER·MEMBER 전원이다.
하루 한 번이라 **알림함에도 남긴다** (재촉 알림처럼 쌓이지 않는다).
당일 축하 모달은 앱이 연다 (`GET /birthdays/today`).
"""

import logging
from datetime import datetime, timedelta, timezone

from app.core.periods import KST
from app.db.session import SessionLocal
from app.services import notification_texts as ntext
from app.services.birthdays import born_on, everyone
from app.services.notifications import notify

logger = logging.getLogger(__name__)


async def birthday_alerts(now: datetime | None = None) -> None:
    """[now] 는 테스트에서 시계를 옮기려고 받는다."""
    today = (now or datetime.now(timezone.utc)).astimezone(KST).date()
    async with SessionLocal() as db:
        tomorrow = await born_on(db, today + timedelta(days=1))
        todays = await born_on(db, today)
        if not tomorrow and not todays:
            return
        people = await everyone(db)
        for person in tomorrow:
            for other in people:
                if other.id != person.id:
                    await notify(db, employee_id=other.id, **ntext.birthday_eve(person.name))
        for person in todays:
            for other in people:
                text = (
                    ntext.birthday_self(person.name)
                    if other.id == person.id
                    else ntext.birthday_today(person.name)
                )
                await notify(db, employee_id=other.id, **text)
        await db.commit()
        logger.info(
            "birthday_alerts: 내일 %d명 · 오늘 %d명 → %d명에게", len(tomorrow), len(todays), len(people)
        )
