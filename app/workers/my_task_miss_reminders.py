"""개인 업무 누락 **매시간 재촉** — 확정될 때까지 (2026-08-31 대표 결정).

퇴근할 때 오는 알림 한 번으로는 놓친다. 그날 못 한 일은 **다음 근무일까지**
만회할 수 있는데, 그 사이에 아무 소리가 없으면 그대로 −20점이 된다.

```
금 18:00 퇴근 · 대청소 안 함     → 19시부터 매시간
토·일 (쉬는 날)                  → 조용하다 — 기회를 안 쓰는 날이다
월 00시부터                      → 마지막 기회라 **하루 내내** 매시간
월에 체크하면                    → 그 자리에서 멎는다
안 하면 화 00:30                 → 확정 −20 (`my_task_miss_scan`)
```

## 시간대를 안 자른다

동료평가 재촉은 KST 09~23 인데 여기는 **24시간**이다 (2026-08-31 대표 결정 —
"확정 전까지는 1시간마다 그냥"). 누락은 퇴근한 **뒤에** 나는 일이라 밤을
빼면 저녁에 한두 번 울리고 끝난다.

쉬는 날이 저절로 조용해지는 것이 이 잡의 안전장치다 — 그날 목록이 비어서
`missing_now` 가 아무도 안 돌려준다.

## 본인에게만 간다

대표·관리자·점장은 **퇴근 스캔 때 한 번**만 받는다 (`_notify_task_missing`).
남의 누락으로 밤새 폰이 울리면 안 된다 — 세 명이 누락하면 대표 넷 × 24회 ×
세 명이다. 점장도 **본인 업무를 빠뜨렸을 때는** 여기에 든다.

## 알림함에 안 남긴다 — 푸시만

하루 스물몇 번이라 남기면 알림함이 통째로 밀려난다. 동료평가 재촉·프로젝트
마감 D-N 과 같은 규칙이다. 놓쳤을 때는 앱을 열 때 뜨는 **누락 모달**이 받는다.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Role
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.my_tasks import missing_now
from app.services.notifications import send_push

logger = logging.getLogger(__name__)


async def my_task_miss_reminders(now: datetime | None = None) -> None:
    """[now] 는 테스트에서 시계를 옮기려고 받는다."""
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    today = now_kst.date()

    async with SessionLocal() as db:
        people = list(
            await db.scalars(
                select(Employee).where(
                    Employee.status == EmployeeStatus.ACTIVE,
                    Employee.deleted_at.is_(None),
                    # 대표·관리자는 내 업무 화면이 없다 — 늘 0개다
                    Employee.role.notin_([Role.MASTER, Role.ADMIN]),
                )
            )
        )
        if not people:
            return

        found = await missing_now(db, people, today)
        for pid, tasks in found.items():
            await send_push(
                db,
                employee_id=pid,
                **ntext.my_task_missing([t.content for t in tasks]),
            )
        # send_push 가 죽은 구독을 지울 수 있어 커밋은 부르는 쪽 몫이다
        await db.commit()
        if found:
            logger.info("my_task_miss_reminders: %d명에게 보냄", len(found))
