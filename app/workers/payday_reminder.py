"""급여날 알림 잡 — 지급일 당일 대상 직원에게 '급여 신청' 알림(+웹푸시).

매일 1회 실행(scheduler). 오늘이 지급일인 급여 월이 있으면, 급여 대상 직급(정책 있는)이고
아직 제출/승인하지 않은 재직 직원에게 in-app 알림(type=PAYROLL)을 적립한다.
(웹푸시 구독이 있으면 notify() 가 best-effort 로 함께 발송.)
"""

from datetime import date

from sqlalchemy import select

from app.core.periods import period_range
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, PayslipStatus
from app.models.org.employee import Employee
from app.models.payroll.payslip import Payslip
from app.services.notifications import notify
from app.services.payroll import due_year_month, ensure_rank_policies, get_rank_policy


async def payday_reminders(today: date | None = None) -> None:
    """지급일 당일 급여 대상 직원에게 신청 알림. today 생략 시 서버 오늘."""
    today = today or date.today()
    year_month = due_year_month(today)
    if year_month is None:
        return
    start, _ = period_range(year_month)
    async with SessionLocal() as db:
        await ensure_rank_policies(db)
        employees = (
            await db.execute(
                select(Employee).where(
                    Employee.status == EmployeeStatus.ACTIVE,
                    Employee.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for emp in employees:
            policy = await get_rank_policy(db, emp.rank, emp.branch_id, start)
            if policy is None:
                continue  # 급여 대상 아님(개발자·대표)
            existing = (
                await db.execute(
                    select(Payslip).where(
                        Payslip.employee_id == emp.id, Payslip.year_month == year_month
                    )
                )
            ).scalar_one_or_none()
            if existing and existing.status in (PayslipStatus.SUBMITTED, PayslipStatus.APPROVED):
                continue  # 이미 신청/승인함
            await notify(
                db,
                employee_id=emp.id,
                type="PAYROLL",
                title="오늘 급여를 신청하세요",
                body=f"{year_month} 급여 지급일이에요. 급여명세서를 확인하고 신청해주세요.",
                link="/payroll",
            )
        await db.commit()
