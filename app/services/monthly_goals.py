"""이달의 목표 — 누가 적어야 하고 언제부터 재촉하나.

앱 모달(`GET /goals/me` 의 `due`)과 첫 월요일 푸시가 **같은 판단**을 쓴다.
갈리면 폰은 울리는데 앱을 열면 아무것도 안 뜬다.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import KST
from app.enums import EmployeeStatus, Role
from app.models.staff.employee import Employee
from app.models.staff.monthly_goal import MonthlyGoal

#: 목표를 적는 사람 — 대표·관리자는 보는 쪽이다
GOAL_ROLES = (Role.MANAGER, Role.MEMBER)
#: 최소 몇 개 (2026-09-28 대표 요청)
GOAL_MIN_ITEMS = 2
GOAL_MAX_ITEMS = 10
GOAL_MAX_LEN = 200


def today_kst(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(KST).date()


def year_month(day: date) -> str:
    return f"{day:%Y-%m}"


def previous_month(ym: str) -> str:
    year, month = (int(p) for p in ym.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def can_check(ym: str, today: date) -> bool:
    """달성 체크를 켰다 껐다 할 수 있나 — **그 달과 다음 달까지.**

    말일에 이룬 것을 다음 달 초에 체크할 수 있어야 한다. 그보다 오래된 달을
    뒤늦게 고치면 지난 달성률이 계속 바뀐다.
    """
    now = year_month(today)
    return ym in (now, previous_month(now))


def first_monday(day: date) -> date:
    """그 달의 첫 번째 월요일 — 목표를 적으라고 알리는 날이다."""
    first = day.replace(day=1)
    return first + timedelta(days=(7 - first.weekday()) % 7)


def writes_goal(employee: Employee) -> bool:
    return employee.role in GOAL_ROLES and employee.status == EmployeeStatus.ACTIVE


async def goal_of(db: AsyncSession, employee_id: str, ym: str) -> MonthlyGoal | None:
    return await db.scalar(
        select(MonthlyGoal).where(
            MonthlyGoal.employee_id == employee_id, MonthlyGoal.year_month == ym
        )
    )


async def missing_now(db: AsyncSession, day: date) -> list[Employee]:
    """이번 달 목표를 아직 안 적은 사람 — 첫 월요일 푸시가 쓴다."""
    written = select(MonthlyGoal.employee_id).where(MonthlyGoal.year_month == year_month(day))
    rows = await db.scalars(
        select(Employee).where(
            Employee.role.in_(GOAL_ROLES),
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.id.not_in(written),
        )
    )
    return list(rows)
