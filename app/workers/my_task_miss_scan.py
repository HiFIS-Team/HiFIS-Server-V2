"""개인 업무 **확정 누락** 판정 (2026-08-21 대표 결정).

퇴근할 때 오는 빨간 알림(`_notify_task_missing`)은 아직 누락이 아니다.
못 한 일은 **다음 근무일에 한 번 더** 목록에 서고, 그 날까지도 안 하면
그때 확정된다. 여기가 그 판정을 한다.

## '24시간' 을 '다음 근무일' 로 읽는다

글자대로 24시간을 재면 **금요일 누락이 토요일 아침에 확정**된다 — 쉬는 날이라
손쓸 방법이 없는데 깎인다. 이월이 이미 근무일로만 내려앉으므로
(`services/my_tasks.py`) 그 결에 맞춘다.

```
금  대청소 ○ 안 함        빨간 알림
토·일 (쉬는 날)           안 센다 — 기회를 안 쓴 날이다
월  대청소 ○ 또 섬        여기서 체크하면 회복
    안 하면                → 화요일 이 잡이 **금요일**을 확정으로 남긴다
```

## 어떻게 아나 — 이틀치 '안 한 것'을 겹쳐 본다 (`services/my_tasks.carried_over`)

```
left(D)  ∩  left(D')  →  D 확정 누락        D' = D 다음 근무일
```

`carried_from` 으로 가르려다 틀렸다. **매일 하는 업무는 그 값이 안 붙는다** —
매일 제 차례라 '밀려 온 것'이 아니라 그냥 또 서기 때문이다
(`due_tasks` 의 `standing` 검사). 지금 업무는 거의 다 매일이라 그걸로 갈랐으면
판정이 한 건도 안 걸렸다.

그래서 요일 업무든 매일 업무든 똑같이 다루는 값 하나만 쓴다 — **그날 안 한 것**
(`DueDay.left`). 그게 이틀 연속 걸리면 첫날이 확정 누락이다.

**셈은 서비스가 한다.** 매시간 재촉(`my_task_miss_reminders`)이 "오늘이 마지막
기회인가" 를 물을 때 같은 함수를 쓴다 — 여기서 따로 셈하면 재촉이 멎었는데
점수가 깎이거나, 안 깎이는데 밤새 울린다.

## 대표·관리자는 대상이 아니다

내 업무 화면이 아예 없어서 늘 0개다. 결근 알림(`absence_alerts`)과 같은
이유로 여기서도 뺀다. 업무를 하나도 안 정한 사람도 조용하다 — 할 일을
안 만든 것이지 안 한 것이 아니다 (`left` 가 비어서 저절로 빠진다).
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Role, ScoreCategory
from app.models.scoring.my_task import MyTaskMiss
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.my_tasks import carried_over
from app.services.notifications import notify
from app.services.scoring import accrue_score

logger = logging.getLogger(__name__)

#: 확정 누락 하루당 당사자 감점 — **고정이다** (2026-08-21 결정).
#:
#: 지각(`LATE_PENALTY`)처럼 누적으로 세지 않는다. 대표가 "-20점 고정"으로
#: 정했다. 그날 몇 개를 빠뜨렸든 한 번 -20 이다.
TASK_MISS_POINTS = -20

#: 이 날부터 센다 — **그 전 날짜는 확정하지 않는다** (2026-08-21 결정).
#:
#: 규칙이 없던 때의 누락까지 거슬러 깎으면 몰랐던 일로 점수와 급여가 깎인다.
#: 점장 기본급 차감(`services/payroll.py`)도 같은 날부터 센다.
STARTS_ON = date(2026, 9, 1)


async def my_task_miss_scan(now: datetime | None = None) -> None:
    """어제까지 보고 **그 앞 근무일**의 누락을 확정한다 — 하루 한 번.

    [now] 는 테스트에서 시계를 옮기려고 받는다.
    """
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    yesterday: date = now_kst.date() - timedelta(days=1)

    async with SessionLocal() as db:
        people = list(
            await db.scalars(
                select(Employee).where(
                    Employee.status == EmployeeStatus.ACTIVE,
                    Employee.deleted_at.is_(None),
                    # 대표·관리자는 내 업무 화면이 없다 — 판정 대상이 아니다
                    Employee.role.notin_([Role.MASTER, Role.ADMIN]),
                )
            )
        )
        # **판정은 서비스가 한다** (`services/my_tasks.py`). 매시간 재촉이 같은
        # 함수를 쓴다 — 여기서 따로 셈하면 재촉이 멎었는데 점수가 깎인다
        by_id = {p.id: p for p in people}
        found: list[tuple[Employee, date, list[str]]] = [
            (by_id[pid], c.since, [t.content for t in c.tasks])
            for pid, c in (await carried_over(db, people, yesterday)).items()
            # 규칙이 없던 때의 누락까지 거슬러 깎지 않는다
            if c.since >= STARTS_ON
        ]
        if not found:
            return

        # 이미 남긴 것은 건너뛴다 — 안 한 채로 며칠이 지나면 같은 날을 또 집는다
        known = {
            (row[0], row[1])
            for row in (
                await db.execute(
                    select(MyTaskMiss.employee_id, MyTaskMiss.date).where(
                        MyTaskMiss.employee_id.in_([p.id for p, _, _ in found]),
                        MyTaskMiss.date.in_([d for _, d, _ in found]),
                    )
                )
            ).all()
        }

        made = 0
        for person, missed_on, contents in found:
            if (person.id, missed_on) in known:
                continue
            miss = MyTaskMiss(
                employee_id=person.id,
                branch_id=person.branch_id,
                date=missed_on,
                task_count=len(contents),
                contents=contents,
            )
            db.add(miss)
            await db.flush()
            event = await accrue_score(
                db,
                employee_id=person.id,
                branch_id=person.branch_id,
                category=ScoreCategory.TASK_MISS,
                points=TASK_MISS_POINTS,
                source_ref_id=f"taskmiss:{missed_on.isoformat()}",
                reason=f"{missed_on.month}월 {missed_on.day}일 개인 업무 누락",
            )
            if event is not None:
                await db.flush()
                miss.score_event_id = event.id
            await notify(
                db, employee_id=person.id, **ntext.task_miss_confirmed(missed_on, contents)
            )
            made += 1

        if made:
            await db.commit()
            logger.info("my_task_miss_scan: 확정 누락 %d건", made)
