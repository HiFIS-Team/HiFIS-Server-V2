"""동료평가 미제출 감점 — 창이 닫힌 직후 한 번 (2026-08-31 대표 결정).

```
  8/31 열림  →  9/1 열림  →  9/2 00:30  여기서 판정
```

## 하나라도 안 냈으면 -20

대상 전원(같은 지점 현장 인원 + 본인)을 다 내야 통과다. 아홉 중 여덟만
내도 깎인다 — 화면의 진행률 막대가 이미 '다 내기' 를 목표로 그리고 있다.

**사람 수로 곱하지 않는다.** 몇 명을 빠뜨렸든 한 번 -20 이다. 곱하면 인원이
많은 지점이 같은 게으름에 더 크게 깎인다 (화순 4명 vs 첨단).

## 첫 창은 안 깎는다

`PEER_MISS_STARTS_ON` 전의 창은 열리기만 하고 감점이 없다. 규칙을 만든 날이
마침 말일이라, 바로 적용하면 하루 전에 안 사람들이 깎인다.

## 두 번 안 깎는다

점수 원장의 `source_ref_id = "peermiss:{기간}"` 하나로 막는다. 따로 표를 두지
않는다 — 개인 업무 누락(`MyTaskMiss`)은 앱이 누락 내역을 그려서 표가 필요했는데
여기는 보여줄 화면이 없다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import ScoreCategory
from app.models.scoring.score_event import ScoreEvent
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.peer_reviews import (
    PEER_MISS_POINTS,
    PEER_MISS_STARTS_ON,
    missing_targets,
    period_of_window,
    reviewers,
)
from app.services.scoring import accrue_score

logger = logging.getLogger(__name__)


async def peer_review_miss_scan(now: datetime | None = None) -> None:
    """어제 닫힌 창을 판정한다 — 하루 한 번. [now] 는 테스트용."""
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    closed = now_kst.date() - timedelta(days=1)  # 어제 = 창의 마지막 날이어야 한다
    if closed.day != 1:
        return
    last_day = closed - timedelta(days=1)  # 그 앞이 말일
    if last_day < PEER_MISS_STARTS_ON:
        logger.info("peer_review_miss_scan: %s 창은 감점 시작 전이라 건너뜀", last_day)
        return
    period = period_of_window(last_day)
    if period is None:  # 달력이 이상할 때의 방어 — 정상 경로에서는 안 걸린다
        return

    ref = f"peermiss:{period}"
    async with SessionLocal() as db:
        already = set(
            await db.scalars(
                select(ScoreEvent.employee_id).where(ScoreEvent.source_ref_id == ref)
            )
        )
        made = 0
        for person in await reviewers(db):
            if person.id in already:
                continue
            missing = await missing_targets(db, person, period)
            if not missing:
                continue
            event = await accrue_score(
                db,
                employee_id=person.id,
                branch_id=person.branch_id,
                category=ScoreCategory.PEER_MISS,
                points=PEER_MISS_POINTS,
                source_ref_id=ref,
                period=period,
                reason=f"{period} 동료평가 미제출",
            )
            if event is None:  # 대표·관리자 — 원장에 안 쌓이므로 알림도 안 보낸다
                continue
            await notify(
                db,
                employee_id=person.id,
                **ntext.peer_review_missed(period, len(missing), PEER_MISS_POINTS),
            )
            made += 1

        if made:
            await db.commit()
            logger.info("peer_review_miss_scan: %s 미제출 %d명 감점", period, made)
