"""세션 싸인 재촉 — 운동일지를 쓰고 **30분 안에** 싸인을 안 받았으면 (2026-10-15 요청).

트레이너가 일지를 먼저 쓰는 사이 회원이 다른 데로 가 버리면 싸인을 잊는다.

```
10:00 PT 일지 작성       → 10:30 첫 푸시 → 11:30 → 12:30 … (1시간마다)
그 회원 싸인이 오늘 찍히면 → 그 자리에서 멎는다
자정                     → 멎는다 (오늘 쓴 일지만 본다)
```

- **오늘 쓴 PT 일지만** — 밀린 일지를 나중에 채운 것(`performed_on` 이 지난날)은
  이미 지나간 수업이라 지금 싸인을 받을 수 없다
- **그 회원의 싸인이 오늘 하나라도 있으면** 안 보낸다 — 싸인을 먼저 받고
  일지를 나중에 쓴 경우도 여기서 빠진다
- **푸시만** — 알림함에 남기지 않는다 (매시간 재촉은 다 그렇다)

## 기록 없이 1시간 간격을 맞춘다

5분마다 돌면서 **일지를 쓴 지 30·90·150…분이 지난 5분 칸**에만 보낸다
([is_due]). 보낸 시각을 따로 저장하지 않아도 한 시간에 한 번이다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import WorkoutKind
from app.models.members.member import Member
from app.models.members.session_sign import SessionSign
from app.models.members.workout import WorkoutLog
from app.services import notification_texts as ntext
from app.services.notifications import send_push

logger = logging.getLogger(__name__)

FIRST_AFTER_MIN = 30
EVERY_MIN = 60
#: 잡이 도는 간격 — scheduler 의 `minute="*/5"` 와 같아야 한다
TICK_MIN = 5


def is_due(written_at: datetime, now: datetime) -> bool:
    """일지를 쓴 지 30분, 그 뒤로 60분마다 돌아오는 5분 칸 안인가.

    ponytail: 잡이 한 칸을 통째로 늦게 돌면 그 시간 것은 건너뛴다 — 재촉이라 괜찮다.
    """
    minutes = (now - written_at).total_seconds() / 60
    return minutes >= FIRST_AFTER_MIN and (minutes - FIRST_AFTER_MIN) % EVERY_MIN < TICK_MIN


async def session_sign_reminders(now: datetime | None = None) -> None:
    """[now] 는 테스트에서 시계를 옮기려고 받는다."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    midnight = datetime(today.year, today.month, today.day, tzinfo=KST)

    async with SessionLocal() as db:
        signed_today = exists().where(
            SessionSign.member_id == WorkoutLog.member_id,
            SessionSign.signed_at >= midnight,
        )
        rows = (
            await db.execute(
                select(WorkoutLog.author_id, WorkoutLog.member_id, WorkoutLog.created_at, Member.name)
                .join(Member, Member.id == WorkoutLog.member_id)
                .where(
                    WorkoutLog.kind == WorkoutKind.PT,
                    WorkoutLog.author_id.is_not(None),
                    WorkoutLog.performed_on == today,
                    WorkoutLog.created_at >= midnight,
                    WorkoutLog.created_at <= now - timedelta(minutes=FIRST_AFTER_MIN),
                    ~signed_today,
                )
                .order_by(WorkoutLog.created_at)
            )
        ).all()

        # 같은 회원 일지가 둘이면 먼저 쓴 것 기준 — 한 시간에 한 번만 울린다
        first: dict[tuple[str, str], tuple[datetime, str]] = {}
        for author_id, member_id, created_at, name in rows:
            first.setdefault((author_id, member_id), (created_at, name))

        sent = 0
        for (author_id, _), (created_at, name) in first.items():
            if is_due(created_at, now):
                await send_push(db, employee_id=author_id, **ntext.session_sign_missing(name))
                sent += 1
        await db.commit()
        if sent:
            logger.info("session_sign_reminders: %d건", sent)
