"""그날 생일인 사람 — 알림 잡과 축하 모달이 같이 쓴다 (2026-09-27).

판정은 `workdays.is_birthday` 와 같다 — **월·일만 본다**, 2월 29일은 평년에
안 걸린다. 재직 중인 사람만.
"""

from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EmployeeStatus
from app.models.staff.employee import Employee


def _active():
    return select(Employee).where(
        Employee.deleted_at.is_(None), Employee.status == EmployeeStatus.ACTIVE
    )


async def born_on(db: AsyncSession, day: date) -> list[Employee]:
    """그날 생일인 재직자."""
    return list(
        await db.scalars(
            _active().where(
                Employee.birthday.is_not(None),
                extract("month", Employee.birthday) == day.month,
                extract("day", Employee.birthday) == day.day,
            )
        )
    )


async def everyone(db: AsyncSession) -> list[Employee]:
    """알림을 받을 재직자 전원 — **권한을 안 가린다** (MASTER~MEMBER)."""
    return list(await db.scalars(_active()))
