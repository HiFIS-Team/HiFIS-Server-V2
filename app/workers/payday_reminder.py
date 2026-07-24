"""급여 신청 리마인더 잡 (CLAUDE.md §9.5) — 앱 내 알림 + 웹푸시.

- payday_reminders: 매일 09:05 KST — 오늘이 지급일이면 신청 독려, 내일이 지급일이면 예고.
- payday_deadline_reminders: 지급일 당일 20:00 KST — 아직 미신청인 대상자에게 마감 임박 알림.
급여 대상 = 직급 정책(RankPolicy) 있는 재직 직원(개발자·대표 제외).
"""

from datetime import date, timedelta

from sqlalchemy import select

from app.core.periods import now_kst, period_range
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, PayslipStatus
from app.models.org.employee import Employee
from app.models.payroll.payslip import Payslip
from app.services.notifications import notify
from app.services.payroll import due_year_month, ensure_rank_policies, get_rank_policy


async def _eligible_employees(db, year_month: str) -> list[Employee]:
    """급여 대상(직급 정책 있는) 재직 직원."""
    start, _ = period_range(year_month)
    employees = (
        await db.execute(
            select(Employee).where(
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    out = []
    for emp in employees:
        if await get_rank_policy(db, emp.rank, emp.branch_id, start) is not None:
            out.append(emp)
    return out


async def _submitted(db, employee_id: str, year_month: str) -> bool:
    ps = (
        await db.execute(
            select(Payslip).where(
                Payslip.employee_id == employee_id, Payslip.year_month == year_month
            )
        )
    ).scalar_one_or_none()
    return ps is not None and ps.status in (PayslipStatus.SUBMITTED, PayslipStatus.APPROVED)


async def payday_reminders(today: date | None = None) -> None:
    """아침 리마인더 — 오늘 지급일(미신청 독려) + 내일 지급일(예고)."""
    today = today or now_kst().date()
    async with SessionLocal() as db:
        await ensure_rank_policies(db)
        ym_today = due_year_month(today)
        if ym_today:
            for emp in await _eligible_employees(db, ym_today):
                if await _submitted(db, emp.id, ym_today):
                    continue
                await notify(
                    db, employee_id=emp.id, type="PAYROLL",
                    title="오늘 급여를 신청하세요",
                    body=f"{ym_today} 급여 지급일이에요. 명세서를 확인하고 신청해주세요.",
                    link="/payroll",
                )
        ym_tomorrow = due_year_month(today + timedelta(days=1))
        if ym_tomorrow:
            for emp in await _eligible_employees(db, ym_tomorrow):
                await notify(
                    db, employee_id=emp.id, type="PAYROLL",
                    title="내일 급여 신청일이에요",
                    body=f"{ym_tomorrow} 급여 지급일은 내일이에요. 미리 확인해두세요.",
                    link="/payroll",
                )
        await db.commit()


async def payday_deadline_reminders(today: date | None = None) -> None:
    """지급일 당일 20:00 KST — 아직 미신청인 대상자에게 마감 임박 알림."""
    today = today or now_kst().date()
    async with SessionLocal() as db:
        await ensure_rank_policies(db)
        ym = due_year_month(today)
        if ym is None:
            return
        for emp in await _eligible_employees(db, ym):
            if await _submitted(db, emp.id, ym):
                continue
            await notify(
                db, employee_id=emp.id, type="PAYROLL",
                title="급여 신청 마감 임박 (오늘 20시)",
                body=f"{ym} 급여를 아직 신청하지 않았어요. 오늘 안에 신청해주세요.",
                link="/payroll",
            )
        await db.commit()
