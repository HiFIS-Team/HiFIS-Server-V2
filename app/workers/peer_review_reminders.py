"""동료평가 재촉 — 평가 창(말일·1일) 동안 **매시간** (2026-08-31 대표 결정).

창이 이틀뿐이라 놓치면 그대로 감점이다. KST 09~23 매시 정각에 **아직 안 낸
사람에게만** 보낸다.

## 알림함에 안 남긴다 — 푸시만

이틀에 서른 번이라 알림함에 남기면 다른 알림이 통째로 밀려난다. 프로젝트
마감 D-N 과 같은 규칙이다(`project_reminders`). 놓쳤을 때를 앱을 열 때 뜨는
**재촉 모달**이 받는다 — 말일 3시간마다 · 1일 매시간.

## 다 낸 사람에게는 안 간다

`missing_targets` 가 비면 건너뛴다. 다 낸 사람에게 "내라" 고 보내면 다음부터
아무도 안 읽는다.

## 대표·관리자는 대상이 아니다

평가를 쓰지도 받지도 않는다 (`REVIEW_ROLES`). 결근 알림과 같은 이유다.
"""

import logging
from datetime import datetime, timezone

from app.core.periods import KST
from app.db.session import SessionLocal
from app.services import notification_texts as ntext
from app.services.notifications import send_push
from app.services.peer_reviews import (
    REMIND_FROM_HOUR,
    REMIND_TO_HOUR,
    missing_targets,
    period_of_window,
    reviewers,
)

logger = logging.getLogger(__name__)


async def peer_review_reminders(now: datetime | None = None) -> None:
    """[now] 는 테스트에서 시계를 옮기려고 받는다."""
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    today = now_kst.date()
    period = period_of_window(today)
    if period is None:
        return
    # 크론이 이미 걸러 주지만 여기서도 본다 — 잡을 손으로 부를 때가 있다
    if not REMIND_FROM_HOUR <= now_kst.hour <= REMIND_TO_HOUR:
        return

    # 말일이면 내일(1일)이 마지막, 1일이면 오늘이 마지막이다
    last_day = today.day != 1

    async with SessionLocal() as db:
        sent = 0
        for person in await reviewers(db):
            missing = await missing_targets(db, person, period)
            if not missing:
                continue
            await send_push(
                db,
                employee_id=person.id,
                **ntext.peer_review_due(period, len(missing), last_day),
            )
            sent += 1
        # send_push 가 죽은 구독을 지울 수 있어 커밋은 부르는 쪽 몫이다
        await db.commit()
        if sent:
            logger.info("peer_review_reminders: %s %d명에게 보냄", period, sent)
