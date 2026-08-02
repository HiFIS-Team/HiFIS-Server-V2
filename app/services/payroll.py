"""급여 산출 서비스 — CLAUDE.md §5.

gross = 기본급 + PT 커미션(세션 싸인당 한 회 단가 × 요율).
커미션: 워크인(신규·소개 없음)=40% / 재등록=50% / 지인소개(소개자 있음)=무조건 50%.
  한 회 단가 = 등록 결제액 ÷ 총 회차. 세션지에 회원 싸인이 찍힐 때마다(SessionSign) 트레이너 몫 적립.
직급별 기본급/요율은 BASE_RANK_POLICIES(전사 기본, 자동 시드) — 지점 예외는 RankPolicy(branch_id).
공제: FREELANCE 3.3% / INSURANCE 4대보험(근로자 부담 근사치).
⚠️ 4대보험 요율은 연도별 변동 — §7 요율 미확정. 확정 시 아래 상수 갱신.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import period_range
from app.enums import DeductionMethod, EmployeeStatus, Rank, RegistrationType, ScoreCategory
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.payroll.payslip import Payslip
from app.models.payroll.rank_policy import RankPolicy
from app.models.members.registration import Registration
from app.models.scoring.score_event import ScoreEvent
from app.models.members.session_sign import SessionSign
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


# 직급별 전사 기본 급여 정책 (기본급, 워크인 요율, 재등록/지인소개 요율).
# 개발자·대표(ADMIN)는 PT 급여 대상 아님 → 정책 없음(마감에서 건너뜀).
# FC = 세전 210만 + FC권 매출(별도·미모델링) → PT 세션 커미션 없음(요율 0).
_POLICY_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)
BASE_RANK_POLICIES: dict[Rank, tuple[int, float, float]] = {
    Rank.TRAINER: (800_000, 0.40, 0.50),
    Rank.FC: (2_100_000, 0.0, 0.0),
    Rank.TEAM_LEAD: (1_500_000, 0.40, 0.50),
    Rank.STORE_MANAGER: (2_000_000, 0.40, 0.50),
}


async def ensure_rank_policies(db: AsyncSession) -> None:
    """전사 기본 급여 정책 자동 시드 (멱등). DB 초기화 후에도 첫 마감 때 복구."""
    existing = {
        r
        for (r,) in (
            await db.execute(select(RankPolicy.rank).where(RankPolicy.branch_id.is_(None)))
        ).all()
    }
    for rank, (base, new_rate, renewal_rate) in BASE_RANK_POLICIES.items():
        if rank not in existing:
            db.add(
                RankPolicy(
                    rank=rank,
                    base_salary=base,
                    new_rate=new_rate,
                    renewal_rate=renewal_rate,
                    branch_id=None,
                    effective_from=_POLICY_EPOCH,
                )
            )
    await db.flush()


# ── 지급일(급여날) ──
def _last_day(year: int, month: int) -> int:
    nxt = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    return nxt.day


def compute_payday(year_month: str) -> date:
    """해당 월 급여 지급일. 기본 = **말일**.
    ⚠️ 지점×직급별 규칙(화순=말일 / 동광주·첨단: FC 말일·트레이너 익월10일)은 실제 지점 등록 후
    지점 설정으로 확장할 것 — 현재는 전 지점·전 직급 말일 기본.
    """
    y, m = int(year_month[:4]), int(year_month[5:7])
    return date(y, m, _last_day(y, m))


def payday_window(year_month: str, today: date) -> dict:
    """급여 신청 창 — 지급일 당일만 열림(전날까지 막힘)."""
    payday = compute_payday(year_month)
    return {"year_month": year_month, "payday": payday.isoformat(), "is_open": today == payday}


def due_year_month(today: date) -> str | None:
    """오늘이 지급일인 급여 월(YYYY-MM). 기본(말일): 오늘이 그 달 말일이면 그 달.
    (익월10일 규칙 대비 지난 달도 후보 — compute_payday 가 지점×직급 규칙으로 확장되면 그대로 반영.)"""
    y, m = today.year, today.month
    prev = f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"
    for cand in (f"{y:04d}-{m:02d}", prev):
        if compute_payday(cand) == today:
            return cand
    return None


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
    # PT 커미션 = 이 트레이너가 **수행한 세션 싸인마다** (한 회 단가 × 요율).
    # 한 회 단가 = 등록 결제액 ÷ 총 회차. 지인소개(회원 소개자 있음)면 무조건 재등록요율(50%),
    # 아니면 워크인(NEW)=신규요율(40%) / 재등록(RENEWAL)=재등록요율(50%).
    signs = (
        await db.execute(
            select(SessionSign)
            .where(
                SessionSign.performed_by_trainer_id == employee.id,
                SessionSign.signed_at >= start,
                SessionSign.signed_at < end,
            )
            .order_by(SessionSign.signed_at)
        )
    ).scalars().all()

    reg_cache: dict[str, Registration | None] = {}
    mem_cache: dict[str, Member | None] = {}
    new_items: list[dict] = []      # 워크인 40%
    renewal_items: list[dict] = []  # 재등록·지인소개 50%
    new_base = 0
    renewal_base = 0
    for sign in signs:
        if sign.registration_id not in reg_cache:
            reg_cache[sign.registration_id] = await db.get(Registration, sign.registration_id)
        reg = reg_cache[sign.registration_id]
        if reg is None or reg.total_sessions <= 0:
            continue
        if reg.member_id not in mem_cache:
            mem_cache[reg.member_id] = await db.get(Member, reg.member_id)
        member = mem_cache[reg.member_id]
        per_session = round(reg.price_paid / reg.total_sessions)
        referral = member is not None and member.referrer_member_id is not None
        if referral:
            kind = "지인소개"
        elif reg.type == RegistrationType.NEW:
            kind = "워크인"
        else:
            kind = "재등록"
        item = {
            "member_name": member.name if member else "?",
            "pkg": f"{sign.session_no}회차 · {kind}",
            "amount": per_session,
        }
        if referral or reg.type == RegistrationType.RENEWAL:
            renewal_items.append(item)
            renewal_base += per_session
        else:  # 워크인 (NEW · 소개 없음)
            new_items.append(item)
            new_base += per_session

    incentive_new = round(new_base * policy.new_rate)
    incentive_renewal = round(renewal_base * policy.renewal_rate)
    other_allowances = 0
    gross = policy.base_salary + incentive_new + incentive_renewal + other_allowances
    deductions = _deductions(gross, employee.deduction_method)
    total_deduction = sum(line["amount"] for line in deductions)

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
            "new_sales": new_items,
            "renewal_sales": renewal_items,
            "session_signs": len(signs),
        },
    }


async def generate_branch_payslips(
    db: AsyncSession, branch_id: str, year_month: str
) -> list[Payslip]:
    """지점·월 급여 마감 — 명세서 생성(교체) + SALES 자동 기여도 적립. commit 은 호출자."""
    await ensure_rank_policies(db)  # 직급별 기본 정책 자동 시드 (없으면)
    start, end = period_range(year_month)
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

        # SALES 자동 기여도 = 이 달 **등록 매출**(신규+재등록 결제액) 기준 (세션 커미션과 별개)
        sales_total = (
            await db.execute(
                select(func.coalesce(func.sum(Registration.price_paid), 0)).where(
                    Registration.trainer_id == employee.id,
                    Registration.purchased_at >= start,
                    Registration.purchased_at < end,
                )
            )
        ).scalar_one()
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
