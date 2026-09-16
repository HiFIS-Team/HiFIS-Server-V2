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

## 얼마나 깎나 — **쌓인다** (2026-09-16)

`-10 → -20 → -30`. 쉬지 않고 빠뜨리면 무거워지고, **본인 근무일로 닷새를
누락 없이 지나면 다시 -10 부터**다 ([TASK_MISS_PENALTY] · [_miss_nth]).

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
from app.enums import EmployeeStatus, ProjectRequestStatus, Role, ScoreCategory
from app.models.scoring.my_task import MyTaskMiss
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.my_tasks import CARRY_FROM, carried_over, is_workday
from app.services.notifications import notify
from app.services.scoring import accrue_score

logger = logging.getLogger(__name__)

#: 확정 누락 차감 — **지각처럼 쌓인다** (2026-09-16 대표 결정).
#:
#: 2026-08-21 에는 `-20 고정`이었다. 그러면 **늘 빠뜨리는 사람과 처음
#: 빠뜨린 사람이 같은 값을 문다** — 지각 차감(`LATE_PENALTY`)을 누적으로
#: 둔 것과 같은 이유로 갈았다.
#:
#: 마지막 칸을 넘으면 그 값이 계속 붙는다 (`-30` 뒤로는 계속 -30).
#: 그날 몇 개를 빠뜨렸든 하루에 한 번인 것은 그대로다.
TASK_MISS_PENALTY = (-10, -20, -30)

#: 이만큼의 **본인 근무일**을 누락 없이 지나면 처음(-10)으로 돌아간다.
#:
#: 지각에는 없는 규칙이다. 지각은 아침에 한 번 늦는 것이라 한 해에 몇 번이
#: 안 되는데, 업무 누락은 매일 걸리는 일이라 **한 번 -30 에 닿으면 그 뒤로
#: 영영 -30** 이 된다 — 그러면 잘하기 시작해도 달라지는 것이 없어서
#: 쌓아 올린 뜻이 사라진다.
#:
#: **달력 날이 아니라 근무일이다.** 주 3일 일하는 사람에게 달력 5일은
#: 실제로 두 번 나오는 것이라, 쉬어서 아낀 셈이 된다.
TASK_MISS_RESET_WORKDAYS = 5

#: 이 날부터 센다 — **그 전 날짜는 확정하지 않는다** (2026-08-21 결정).
#:
#: 규칙이 없던 때의 누락까지 거슬러 깎으면 몰랐던 일로 점수와 급여가 깎인다.
#: 점장 기본급 차감(`services/payroll.py`)도 같은 날부터 센다.
#:
#: **밀어 오는 기준(`services/my_tasks.CARRY_FROM`)과 같은 값이다.** 데려오지도
#: 않는 날을 감점하거나, 데려와 놓고 감점을 안 하면 어긋난다 — 한 자리에서 가져온다.
STARTS_ON = CARRY_FROM


def _workdays_between(person: Employee, start: date, end: date, *, stop_at: int) -> int:
    """[start] 와 [end] **사이**(양끝 제외)의 그 사람 근무일 수.

    [stop_at] 에 닿으면 그 자리에서 멈춘다 — 몇 달 전 누락과의 간격을
    끝까지 셀 이유가 없다. 근무 요일을 안 정한 사람은 모든 날이 근무일이라
    (`is_workday`) 다섯 번 만에 끝난다.
    """
    count = 0
    day = start + timedelta(days=1)
    while day < end:
        if is_workday(person, day):
            count += 1
            if count >= stop_at:
                return count
        day += timedelta(days=1)
    return count


async def _miss_nth(db, person: Employee, missed_on: date) -> int:
    """이번이 **몇 번째 누락인가** — 스택이 끊긴 자리부터 다시 센다.

    앞의 누락들을 최근 것부터 거슬러 보면서, 두 누락 **사이**에 그 사람
    근무일이 [TASK_MISS_RESET_WORKDAYS] 일 이상 비어 있으면 거기서 끊는다.

    ```
    9/1 누락 · 9/2 누락 · (근무일 5일 이상 조용) · 9/12 누락
                                                  └ 여기는 다시 1회째(-10)
    ```

    **사유가 승인된 날은 안 센다** — 없던 일이 되어 점수도 돌려줬는데
    다음 누락을 무겁게 만들면 되돌린 것이 아니다.

    **규칙 시작일(`STARTS_ON`) 앞은 안 본다.** 그때는 확정 자체를 안 했다.
    """
    earlier = list(
        await db.scalars(
            select(MyTaskMiss)
            .where(
                MyTaskMiss.employee_id == person.id,
                MyTaskMiss.date < missed_on,
                MyTaskMiss.date >= STARTS_ON,
                MyTaskMiss.excuse_status.is_distinct_from(ProjectRequestStatus.APPROVED),
            )
            .order_by(MyTaskMiss.date.desc())
        )
    )
    nth = 1
    prev = missed_on
    for row in earlier:
        gap = _workdays_between(person, row.date, prev, stop_at=TASK_MISS_RESET_WORKDAYS)
        if gap >= TASK_MISS_RESET_WORKDAYS:
            break
        nth += 1
        prev = row.date
    return nth


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
            # **줄을 넣기 전에 센다** — 넣고 세면 이번 것까지 들어가 한 칸 밀린다
            nth = await _miss_nth(db, person, missed_on)
            points = TASK_MISS_PENALTY[min(nth, len(TASK_MISS_PENALTY)) - 1]
            db.add(miss)
            await db.flush()
            event = await accrue_score(
                db,
                employee_id=person.id,
                branch_id=person.branch_id,
                category=ScoreCategory.TASK_MISS,
                points=points,
                source_ref_id=f"taskmiss:{missed_on.isoformat()}",
                reason=f"{missed_on.month}월 {missed_on.day}일 개인 업무 누락 {nth}회",
            )
            if event is not None:
                await db.flush()
                miss.score_event_id = event.id
            await notify(
                db,
                employee_id=person.id,
                **ntext.task_miss_confirmed(missed_on, contents, nth, points),
            )
            made += 1

        if made:
            await db.commit()
            logger.info("my_task_miss_scan: 확정 누락 %d건", made)
