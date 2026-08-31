"""동료평가 기간·대상 (2026-08-31 대표 결정).

## 이틀만 열린다 — **말일과 다음달 1일**

한 달 내내 열어 두면 아무 때나 미루다 결국 아무도 안 낸다. 창을 이틀로
좁히고 그 안에 못 내면 깎는다. 그 이틀이 아니면 서버가 아예 안 받는다.

```
  8/30      8/31            9/1           9/2
  닫힘   →  열림(말일)  →  열림(1일)  →  닫힘
                                          └ 00:30 안 낸 사람 감점
```

## 둘 다 **끝난 달**을 평가한다

9/1 에 쓰는 평가는 9월이 아니라 **8월**에 대한 것이다. 창 하나가 한 달을
맡으므로, 날짜를 그대로 기간으로 쓰면 같은 창이 두 기간으로 갈려서 8/31 에
낸 사람과 9/1 에 낸 사람이 서로 다른 달에 쌓인다.

## 대상은 같은 지점 현장 인원 + 본인

대표·관리자는 운영 전담이라 평가하지도 평가받지도 않는다 (`POST` 권한이
원래 MEMBER·MANAGER 다). 앱의 `_targetsOf` 와 같은 규칙이어야 한다 — 갈리면
화면에는 다 냈다고 나오는데 서버는 안 냈다고 깎는다.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import KST
from app.enums import EmployeeStatus, Role
from app.models.scoring.peer_review import PeerReview
from app.models.staff.employee import Employee

#: 평가를 쓰고 받는 권한 — 앱 `Role.doesFieldWork` 와 같은 값이다
REVIEW_ROLES = (Role.MEMBER, Role.MANAGER)

#: 창이 닫힐 때까지 하나라도 안 냈으면 붙는 감점 (2026-08-31 대표 결정)
#:
#: 개인 업무 누락(`TASK_MISS_POINTS`)과 **같은 -20 고정**이다. 몇 명을
#: 빠뜨렸든 한 번만 깎는다 — 사람 수로 곱하면 인원이 많은 지점이 불리해진다.
PEER_MISS_POINTS = -20

#: 이 말일부터 감점한다 — **그 앞 창은 열리기만 하고 안 깎는다**
#:
#: 규칙을 만든 날이 마침 말일(2026-08-31)이라, 바로 적용하면 하루 전에 안
#: 사람들이 깎인다. 개인 업무 누락이 `2026-09-01` 부터인 것과 같은 이유다.
PEER_MISS_STARTS_ON = date(2026, 9, 30)

#: 재촉 푸시를 보내는 시각 (KST, 양끝 포함) — 매시 정각
REMIND_FROM_HOUR = 9
REMIND_TO_HOUR = 23


def is_last_day(day: date) -> bool:
    """그 달의 마지막 날인가 — 달마다 28·29·30·31 이라 다음 날로 잰다."""
    return (day + timedelta(days=1)).day == 1


def period_of_window(day: date) -> str | None:
    """[day] 가 평가 창이면 **그 창이 평가하는 달**, 아니면 `None`.

    말일이면 그 달, 1일이면 지난달이다 — 이틀이 같은 값을 준다.
    """
    if day.day == 1:
        ended = day - timedelta(days=1)
        return f"{ended:%Y-%m}"
    if is_last_day(day):
        return f"{day:%Y-%m}"
    return None


def open_period(now: datetime | None = None) -> str | None:
    """지금 열려 있는 평가 기간 — 닫혀 있으면 `None`. [now] 는 테스트용."""
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    return period_of_window(now_kst.date())


def latest_period(now: datetime | None = None) -> str:
    """지금 열려 있거나 **가장 최근에 닫힌** 창의 기간 — 늘 값이 있다.

    닫혀 있어도 지난 창에 낸 평가는 읽을 수 있어야 해서 화면이 이 값을 쓴다.
    닫힌 날은 늘 2일~(말일−1)이라 그때의 최근 창은 **지난달**이다.
    """
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    period = period_of_window(now_kst.date())
    if period is not None:
        return period
    first = now_kst.date().replace(day=1)
    return f"{first - timedelta(days=1):%Y-%m}"


async def review_targets(db: AsyncSession, person: Employee) -> list[Employee]:
    """[person] 이 평가해야 할 사람 — 같은 지점 현장 인원(본인 포함).

    대표·관리자면 빈 목록이다 (쓰는 사람이 아니다).
    """
    if person.role not in REVIEW_ROLES:
        return []
    rows = await db.scalars(
        select(Employee).where(
            Employee.branch_id == person.branch_id,
            Employee.role.in_(REVIEW_ROLES),
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.deleted_at.is_(None),
        )
    )
    return list(rows)


async def missing_targets(
    db: AsyncSession, person: Employee, period: str
) -> list[Employee]:
    """아직 평가를 안 낸 대상 — 비어 있으면 다 낸 것이다."""
    targets = await review_targets(db, person)
    if not targets:
        return []
    done = set(
        await db.scalars(
            select(PeerReview.reviewee_id).where(
                PeerReview.reviewer_id == person.id,
                PeerReview.period == period,
            )
        )
    )
    return [t for t in targets if t.id not in done]


async def reviewers(db: AsyncSession) -> list[Employee]:
    """평가를 써야 하는 사람 전원 — 재촉·감점 잡이 훑는 명단."""
    rows = await db.scalars(
        select(Employee).where(
            Employee.role.in_(REVIEW_ROLES),
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.deleted_at.is_(None),
        )
    )
    return list(rows)
