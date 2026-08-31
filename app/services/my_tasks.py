"""내 업무가 어느 날에 서는지 — **판정 규칙을 한 곳에 모은다** (2026-08-20).

같은 질문을 세 곳이 한다.

| 자리 | 무엇 |
|---|---|
| `GET /my-tasks` | 본인 화면의 하루 목록 |
| `GET /my-tasks/roster` | 대표가 보는 사람별 `3/5` |
| `_notify_task_missing` (퇴근 스캔) | 남기고 나갔나 |

**셋이 갈리면 안 된다.** 요일 필터를 넣을 때 실제로 겪었다 — 한 곳만 고치면
화면은 다 했다는데 퇴근할 때 누락 알림이 온다. 그래서 여기 하나를 셋이 쓴다.

## 안 한 일은 다음 근무일로 밀린다 (2026-08-20 요청)

```
금  대청소 ○  ← 안 함
토  (쉬는 날)                    건너뛴다 — 근무일에만 내려앉는다
일  (쉬는 날)
월  세탁 ○ 환기 ○
    ─── 밀린 일 ───
    대청소 ○                     ← 금요일 것이 여기로
```

**행을 새로 만들지 않는다.** 밀린 것은 저장된 값이 아니라 그때그때 셈한
결과다 — `MyTask` 하나와 `MyTaskCheck` 기록만 있으면 어느 날 무엇이 밀렸는지
답이 하나로 정해진다. 행을 만들면 요일을 고치거나 결재로 지웠을 때 이미
만들어 둔 이월분이 남아서 어긋난다.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import LeaveStatus, LeaveType
from app.models.scoring.my_task import MyTask, MyTaskCheck
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.employee import Employee

#: 지난 차례를 며칠까지 거슬러 보나 — **7일이면 충분하다.**
#:
#: 요일이 하나라도 걸려 있으면 지난 차례는 아무리 멀어도 7일 안에 있다
#: (`weekdays` 는 비어 있을 수 없다 — 비면 매일로 본다).
LOOKBACK = 7


@dataclass(frozen=True)
class DueTask:
    """그날 서는 업무 한 줄."""

    task: MyTask
    #: 원래 차례였던 날 — **`None` 이면 그날 제 차례**다.
    #: 값이 있으면 그날 못 해서 밀려 온 것이다 (앱이 구분선 아래에 그린다).
    carried_from: date | None = None


@dataclass(frozen=True)
class DueDay:
    """한 사람의 하루 — **세 곳이 물어보는 것을 한 번에** 돌려준다."""

    #: 제 차례 것 먼저, 밀려 온 것이 뒤
    tasks: list[DueTask]
    #: 그날 체크한 업무 id — 목록을 만들며 같이 받아 둔다 (질의를 또 안 한다)
    checked: set[str]
    #: 종일 월차라 그날 것이 통째로 다음 근무일로 갔나
    moved_out: bool
    total: int
    done: int
    complete: bool

    @property
    def left(self) -> list[MyTask]:
        """아직 안 한 것 — 퇴근 알림이 이걸 읽는다."""
        return [d.task for d in self.tasks if d.task.id not in self.checked]


def is_workday(employee: Employee | None, day: date) -> bool:
    """그 사람의 근무일인가 — `Employee.work_days` (ISO 1~7).

    **설정을 안 했으면 근무일로 본다.** 안 정한 사람을 쉬는 사람으로 치면
    누락이 통째로 사라진다 (근무 요일을 아직 안 넣은 사람이 많다 — 69번).
    """
    days = (employee.work_days if employee else None) or []
    return not days or day.isoweekday() in days


def is_complete(
    total: int,
    done: int,
    employee: Employee | None,
    day: date,
    *,
    moved_out: bool = False,
) -> bool:
    """그날 다 했나.

    | | 업무 0개 | 1개 이상 |
    |---|---|---|
    | 근무일 | **누락** (업무를 정하는 게 필수다) | 다 체크해야 완료 |
    | 쉬는 날 | 완료 (넣는 것이 선택이다) | 넣었으면 체크해야 완료 |
    | **종일 월차** | 완료 — 그날 것은 다음 근무일로 옮겨졌다 | (목록이 빈다) |

    [moved_out] 은 종일 월차라 그날 업무가 통째로 다음 근무일로 간 날이다.
    """
    if moved_out:
        return True
    if total == 0:
        return not is_workday(employee, day)
    return done == total


class _Ledger:
    """한 번 받아 온 체크·휴가 기록 — 사람이 여럿이어도 질의는 몇 개뿐이다."""

    def __init__(
        self,
        checks: list[tuple[str, date]],
        leaves: list[LeaveRequest],
    ) -> None:
        #: 업무별 **마지막으로 체크한 날** (창 안에서)
        self.last_check: dict[str, date] = {}
        #: 그날 체크한 업무들
        self.checked_on: dict[date, set[str]] = {}
        for task_id, when in checks:
            if when > self.last_check.get(task_id, date.min):
                self.last_check[task_id] = when
            self.checked_on.setdefault(when, set()).add(task_id)
        self._leaves = leaves

    def full_day_leave(self, employee_id: str, day: date) -> bool:
        """그날 **종일** 승인 휴가인가.

        **반차는 안 친다.** 반차는 반나절 일하는 날이라 그날 업무를 통째로
        옮기면 반나절치 할 일이 사라진다. 근태 판정(`_attendance_status`)은
        반차도 `ON_LEAVE` 로 묶는데, 여기서는 갈라야 한다.
        """
        return any(
            lv.employee_id == employee_id
            and lv.type != LeaveType.HALF
            and lv.start_date <= day <= lv.end_date
            for lv in self._leaves
        )


async def _ledger(db: AsyncSession, people_ids: list[str], task_ids: list[str], day: date) -> _Ledger:
    since = day - timedelta(days=LOOKBACK)
    checks: list[tuple[str, date]] = []
    if task_ids:
        rows = await db.execute(
            select(MyTaskCheck.my_task_id, MyTaskCheck.date).where(
                MyTaskCheck.my_task_id.in_(task_ids),
                MyTaskCheck.date >= since,
                MyTaskCheck.date <= day,
            )
        )
        checks = [(r[0], r[1]) for r in rows]
    leaves = list(
        await db.scalars(
            select(LeaveRequest).where(
                LeaveRequest.employee_id.in_(people_ids),
                LeaveRequest.status == LeaveStatus.APPROVED,
                LeaveRequest.start_date <= day,
                LeaveRequest.end_date >= since,
            )
        )
    )
    return _Ledger(checks, leaves)


def _last_due(task: MyTask, day: date, created: date) -> date | None:
    """`day` 전에 이 업무가 마지막으로 섰던 날 — 없으면 `None`.

    만든 날보다 앞선 날은 안 본다. 안 그러면 **오늘 만든 업무가 어제 것을
    안 했다고 밀려 온다.**
    """
    days = task.weekdays or []
    for back in range(1, LOOKBACK + 1):
        d = day - timedelta(days=back)
        if d < created:
            return None
        if d.isoweekday() in days:
            return d
    return None


async def due_tasks(
    db: AsyncSession,
    people: list[Employee],
    day: date,
    *,
    today: date,
) -> dict[str, DueDay]:
    """사람별로 **그날 서는 업무**를 준다 — 제 차례 것 + 밀려 온 것.

    밀려 온 것은 제 차례 것 **뒤에** 붙는다 (앱이 구분선 아래에 그린다).

    ## 밀려 오는 조건

    | | |
    |---|---|
    | 내려앉는 날 | **본인 근무일**이고 종일 월차가 아니어야 한다 |
    | 앞으로는 안 민다 | 오지 않은 날은 뭘 빠뜨릴지 알 수 없다 |
    | 겹치면 안 민다 | 그날 제 차례로 이미 서 있으면 두 줄이 된다 |
    | 지난 차례를 했으면 안 민다 | 밀려 온 날 체크한 것도 '했다'로 친다 |
    """
    ids = [p.id for p in people]
    if not ids:
        return {}
    rows = list(
        await db.scalars(
            select(MyTask)
            .where(MyTask.employee_id.in_(ids), MyTask.deleted_at.is_(None))
            .order_by(MyTask.sort, MyTask.created_at)
        )
    )
    mine: dict[str, list[MyTask]] = {i: [] for i in ids}
    for t in rows:
        mine[t.employee_id].append(t)

    book = await _ledger(db, ids, [t.id for t in rows], day)
    iso = day.isoweekday()
    today_checks = book.checked_on.get(day, set())
    out: dict[str, DueDay] = {}

    for person in people:
        tasks = mine[person.id]
        # 종일 월차면 그날 것이 통째로 다음 근무일로 간다 — **여기는 빈다**
        if book.full_day_leave(person.id, day):
            out[person.id] = DueDay([], set(), True, 0, 0, True)
            continue

        scheduled = [t for t in tasks if iso in (t.weekdays or [])]
        due = [DueTask(t) for t in scheduled]

        # 오지 않은 날에는 안 민다. 쉬는 날에도 안 민다 (2026-08-20 요청 —
        # "본인 근무일에만 옮겨져야 한다")
        if day <= today and is_workday(person, day):
            standing = {t.id for t in scheduled}
            for t in tasks:
                if t.id in standing:
                    continue  # 그날 제 차례로 이미 서 있다
                last = _last_due(t, day, t.created_at.date())
                if last is None:
                    continue
                seen = book.last_check.get(t.id)
                if seen is not None and seen >= last:
                    continue  # 그 차례를 했거나, 밀려 온 날 했다
                due.append(DueTask(t, carried_from=last))

        # **밀려 온 것도 같이 센다.** 안 세면 대표 판은 `3/3 완료` 인데
        # 본인 화면은 `3/5` 라 둘이 갈린다
        checked = {d.task.id for d in due if d.task.id in today_checks}
        out[person.id] = DueDay(
            tasks=due,
            checked=checked,
            moved_out=False,
            total=len(due),
            done=len(checked),
            complete=is_complete(len(due), len(checked), person, day),
        )
    return out


def prev_workday(person: Employee, day: date) -> date | None:
    """[day] 바로 앞의 **근무일** — 없으면 `None`.

    쉬는 날은 건너뛴다. 못 한 일을 만회할 기회를 쓰는 날은 근무일뿐이라 그렇다.
    """
    for back in range(1, LOOKBACK + 1):
        d = day - timedelta(days=back)
        if is_workday(person, d):
            return d
    return None


@dataclass(frozen=True)
class Carried:
    """지난 근무일에도 안 했고 그날도 안 한 것 — **그날이 마지막 기회다**."""

    #: 원래 차례였던 날 (지난 근무일)
    since: date
    tasks: list[MyTask]


async def carried_over(
    db: AsyncSession, people: list[Employee], day: date
) -> dict[str, Carried]:
    """마지막 기회를 쓰고 있는 사람 — **확정 판정과 매시간 재촉이 같이 쓴다**.

    | 부르는 곳 | 무엇에 |
    |---|---|
    | `my_task_miss_scan` | 어제까지 안 했으면 그 앞 근무일을 **확정 누락**으로 |
    | `my_task_miss_reminders` | 오늘이 마지막 기회면 **하루 내내** 재촉 |

    **둘이 갈리면 안 된다.** 재촉이 멎었는데 점수가 깎이거나, 안 깎이는데
    밤새 울린다.

    ## `carried_from` 으로 가르면 틀린다

    **매일 하는 업무는 그 값이 안 붙는다** — 매일 제 차례라 '밀려 온 것'이
    아니라 그냥 또 서기 때문이다 (`due_tasks` 의 `standing` 검사). 지금 업무는
    거의 다 매일이라 그걸로 갈랐으면 한 건도 안 걸렸다.

    그래서 요일 업무든 매일 업무든 똑같이 다루는 값 하나만 쓴다 — **그날 안 한
    것**(`DueDay.left`). 그게 이틀(근무일 기준) 연속 걸리면 지난 차례가 지금
    마지막 기회를 쓰고 있는 것이다.
    """
    graced = [p for p in people if is_workday(p, day)]
    if not graced:
        return {}

    # 앞 근무일이 사람마다 다르다 (근무 요일이 다르므로). 같은 날끼리 묶어서
    # 질의를 몇 개로 줄인다 — 사람마다 부르면 23명이면 23번이다
    by_prev: dict[date, list[Employee]] = defaultdict(list)
    for person in graced:
        prev = prev_workday(person, day)
        if prev is not None:
            by_prev[prev].append(person)
    if not by_prev:
        return {}

    left_now = {
        pid: {t.id for t in due.left}
        for pid, due in (await due_tasks(db, graced, day, today=day)).items()
    }
    out: dict[str, Carried] = {}
    for prev, group in by_prev.items():
        for pid, due in (await due_tasks(db, group, prev, today=prev)).items():
            still = [t for t in due.left if t.id in left_now.get(pid, set())]
            if still:
                out[pid] = Carried(since=prev, tasks=still)
    return out


async def _checked_out(db: AsyncSession, people_ids: list[str], day: date) -> set[str]:
    """그날 **퇴근을 찍은** 사람."""
    if not people_ids:
        return set()
    rows = await db.scalars(
        select(Attendance.employee_id).where(
            Attendance.employee_id.in_(people_ids),
            Attendance.date == day,
            Attendance.check_out.is_not(None),
        )
    )
    return set(rows)


async def missing_now(
    db: AsyncSession, people: list[Employee], day: date
) -> dict[str, list[MyTask]]:
    """지금 **누락 경고가 서 있는** 사람 — 매시간 푸시와 앱 모달이 같이 쓴다.

    | 남은 것 | 언제 경고인가 |
    |---|---|
    | 지난 근무일에도 안 한 것이 섞여 있다 | **하루 내내** — 오늘이 마지막 기회다 |
    | 오늘 제 차례 것만 남았다 | **퇴근을 찍은 뒤부터** |

    퇴근 전에도 울리면 아직 일하는 중인 사람을 매시간 쪼는 셈이다. 요청이
    "누락되고 **퇴근이 스캔되면**" 이었다 (2026-08-31 대표 결정).

    **판정을 여기 하나로 둔다.** 매시간 푸시(`my_task_miss_reminders`)와
    앱 모달(`GET /my-tasks/miss-alert`)이 갈리면 폰은 울리는데 앱을 열면
    아무것도 안 뜬다.
    """
    due = await due_tasks(db, people, day, today=day)
    left = {pid: d.left for pid, d in due.items() if d.left}
    if not left:
        return {}
    still = [p for p in people if p.id in left]
    carried = await carried_over(db, still, day)
    gone = await _checked_out(db, list(left), day)
    return {pid: tasks for pid, tasks in left.items() if pid in carried or pid in gone}
