"""급여 산출 서비스 — CLAUDE.md §5.

gross = 기본급 + Σ(신규매출)×newRate + Σ(재등록매출)×renewalRate.
공제: FREELANCE 3.3% / INSURANCE 4대보험(근로자 부담 근사치).
⚠️ 4대보험 요율은 연도별 변동 — §7 요율 미확정. 확정 시 아래 상수 갱신.
"""

from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import period_range
from app.enums import DeductionMethod, EmployeeStatus, RegistrationType, ScoreCategory
from app.models.org.employee import Employee
from app.models.sales.member import Member
from app.models.payroll.payslip import Payslip
from app.models.payroll.rank_policy import RankPolicy
from app.models.sales.registration import Registration
from app.models.scoring.score_event import ScoreEvent
from app.models.sales.session_sign import SessionSign
from app.services.scoring import accrue_score

FREELANCE_RATE = 0.033
# 4대보험 근로자 부담분 근사치 (건강보험 기준 장기요양 별도)
INSURANCE_RATES = (("국민연금", 0.045), ("건강보험", 0.03545), ("고용보험", 0.009))
LONGTERM_CARE_RATE = 0.1295  # 장기요양 = 건강보험료 × 12.95%

# 매출성과(SALES) 자동 기여도 — 최종 점수표:
# 100,000원당 10점(= 매출 ÷ 10,000 이 기본점수) × 0.25. 월 총 PT매출(신규+재등록) 기준.
# 예) 월 총매출 1,000,000원 → 100 × 0.25 = 25점.
SALES_WON_PER_POINT = 10_000  # 10,000원 = 기본 1점 (100,000원 = 10점)
SALES_MULTIPLIER = 0.25


def sales_points(total_sales: int) -> int:
    return round(total_sales / SALES_WON_PER_POINT * SALES_MULTIPLIER)


def _deductions(gross: int, method: DeductionMethod) -> list[dict]:
    if method == DeductionMethod.FREELANCE:
        return [{"label": "사업소득세(3.3%)", "amount": round(gross * FREELANCE_RATE)}]
    lines: list[dict] = []
    health = 0
    for label, rate in INSURANCE_RATES:
        amount = round(gross * rate)
        lines.append({"label": label, "amount": amount})
        if label == "건강보험":
            health = amount
    lines.append({"label": "장기요양보험", "amount": round(health * LONGTERM_CARE_RATE)})
    return lines


async def get_rank_policy(
    db: AsyncSession, rank, branch_id: str, as_of: datetime
) -> RankPolicy | None:
    """지점 우선(branch 지정 > 전사 null), effective_from 이 as_of 이전인 최신 정책."""
    stmt = (
        select(RankPolicy)
        .where(
            RankPolicy.rank == rank,
            RankPolicy.effective_from <= as_of,
            or_(RankPolicy.branch_id == branch_id, RankPolicy.branch_id.is_(None)),
        )
        .order_by(RankPolicy.branch_id.isnot(None).desc(), RankPolicy.effective_from.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def build_payslip_data(
    db: AsyncSession, employee: Employee, year_month: str, policy: RankPolicy
) -> dict:
    start, end = period_range(year_month)
    registrations = (
        await db.execute(
            select(Registration).where(
                Registration.trainer_id == employee.id,
                Registration.purchased_at >= start,
                Registration.purchased_at < end,
            )
        )
    ).scalars().all()

    new_sales: list[dict] = []
    renewal_sales: list[dict] = []
    new_sum = 0
    renewal_sum = 0
    for reg in registrations:
        member = await db.get(Member, reg.member_id)
        item = {
            "member_name": member.name if member else "?",
            "pkg": f"{reg.total_sessions}회",
            "amount": reg.price_paid,
        }
        if reg.type == RegistrationType.NEW:
            new_sales.append(item)
            new_sum += reg.price_paid
        else:
            renewal_sales.append(item)
            renewal_sum += reg.price_paid

    incentive_new = round(new_sum * policy.new_rate)
    incentive_renewal = round(renewal_sum * policy.renewal_rate)
    other_allowances = 0
    gross = policy.base_salary + incentive_new + incentive_renewal + other_allowances
    deductions = _deductions(gross, employee.deduction_method)
    total_deduction = sum(line["amount"] for line in deductions)

    session_signs = (
        await db.execute(
            select(func.count(SessionSign.id)).where(
                SessionSign.performed_by_trainer_id == employee.id,
                SessionSign.signed_at >= start,
                SessionSign.signed_at < end,
            )
        )
    ).scalar_one()

    return {
        "rank": employee.rank,
        "base_salary": policy.base_salary,
        "incentive_new": incentive_new,
        "incentive_renewal": incentive_renewal,
        "other_allowances": other_allowances,
        "gross": gross,
        "deduction_method": employee.deduction_method,
        "deductions": deductions,
        "total_deduction": total_deduction,
        "net": gross - total_deduction,
        "basis": {
            "new_sales": new_sales,
            "renewal_sales": renewal_sales,
            "session_signs": session_signs,
        },
    }


async def generate_branch_payslips(
    db: AsyncSession, branch_id: str, year_month: str
) -> list[Payslip]:
    """지점·월 급여 마감 — 명세서 생성(교체) + SALES 자동 기여도 적립. commit 은 호출자."""
    start, _ = period_range(year_month)
    employees = (
        await db.execute(
            select(Employee).where(
                Employee.branch_id == branch_id,
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if not employees:
        return []

    employee_ids = [employee.id for employee in employees]
    sales_ref = f"sales:{year_month}"
    # 재생성 = 기존 명세서 + 자동 SALES 점수 교체 (멱등)
    await db.execute(
        delete(Payslip).where(
            Payslip.year_month == year_month, Payslip.employee_id.in_(employee_ids)
        )
    )
    await db.execute(
        delete(ScoreEvent).where(
            ScoreEvent.source_ref_id == sales_ref, ScoreEvent.employee_id.in_(employee_ids)
        )
    )

    generated: list[Payslip] = []
    for employee in employees:
        policy = await get_rank_policy(db, employee.rank, employee.branch_id, start)
        if policy is None:
            continue  # 요율 정책 없는 직급은 건너뜀
        data = await build_payslip_data(db, employee, year_month, policy)
        payslip = Payslip(employee_id=employee.id, year_month=year_month, **data)
        db.add(payslip)
        generated.append(payslip)

        sales_total = sum(item["amount"] for item in data["basis"]["new_sales"]) + sum(
            item["amount"] for item in data["basis"]["renewal_sales"]
        )
        if sales_total > 0:
            await accrue_score(
                db,
                employee_id=employee.id,
                branch_id=employee.branch_id,
                category=ScoreCategory.CONTRIB,
                points=sales_points(sales_total),
                source_ref_id=sales_ref,
                period=year_month,
                reason="매출성과(자동)",
            )
    return generated
