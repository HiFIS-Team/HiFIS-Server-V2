"""급여 신청 리마인더 잡 (CLAUDE.md §9.5) — 앱 내 알림 + 웹푸시.

- payday_reminders: 매일 09:05 KST — 오늘이 지급일이면 신청 독려, 내일이 지급일이면 예고.
- payday_deadline_reminders: 지급일 당일 20:00 KST — 아직 미신청인 대상자에게 마감 임박 알림.
급여 대상 = 직급 정책(RankPolicy) 있는 재직 직원(개발자·대표 제외).

**지급일이 사람마다 다르다** — 화순·FC 는 말일, 동광주·첨단 트레이너는 익월 10일.
그래서 "오늘이 지급일인가"를 전사로 한 번 묻지 않고 사람마다 판정한다.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.periods import now_kst, period_range
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, PayslipStatus
from app.models.staff.employee import Employee
from app.models.payroll.payslip import Payslip
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.payroll import (
    due_year_month,
    ensure_rank_policies,
    get_payday_policy,
    get_rank_policy,
    payroll_started,
)


async def _targets(db, today: date) -> list[tuple[Employee, str]]:
    """오늘이 지급일인 사람과 그 명세서 월 — 급여 대상(직급 정책 있는 재직자)만."""
    now = datetime.now(timezone.utc)
    employees = (
        await db.execute(
            select(Employee).where(
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    out: list[tuple[Employee, str]] = []
    for emp in employees:
        payday = await get_payday_policy(db, emp.branch_id, emp.rank, now)
        year_month = due_year_month(today, payday)
        if year_month is None:
            continue  # 이 사람의 지급일이 아니다
        if not payroll_started(year_month, payday):
            continue  # 아직 급여를 재기 시작 전인 주기
        start, _ = period_range(year_month)
        if await get_rank_policy(db, emp.rank, emp.branch_id, start) is None:
            continue  # 요율 정책 없는 직급(개발자·대표)은 대상이 아니다
        out.append((emp, year_month))
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
        for emp, year_month in await _targets(db, today):
            if await _submitted(db, emp.id, year_month):
                continue
            await notify(db, employee_id=emp.id, **ntext.payday_today(year_month))
        for emp, year_month in await _targets(db, today + timedelta(days=1)):
            await notify(db, employee_id=emp.id, **ntext.payday_tomorrow(year_month))
        await db.commit()


async def payday_deadline_reminders(today: date | None = None) -> None:
    """지급일 당일 20:00 KST — 아직 미신청인 대상자에게 마감 임박 알림."""
    today = today or now_kst().date()
    async with SessionLocal() as db:
        await ensure_rank_policies(db)
        for emp, year_month in await _targets(db, today):
            if await _submitted(db, emp.id, year_month):
                continue
            await notify(db, employee_id=emp.id, **ntext.payday_deadline(year_month))
        await db.commit()
