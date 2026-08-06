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
from app.enums import (
    DeductionMethod,
    EmployeeStatus,
    EmploymentType,
    Rank,
    RegistrationType,
    ScoreCategory,
)
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.payroll.payslip import Payslip
from app.models.payroll.hourly_wage import HourlyWagePolicy
from app.models.payroll.payday_policy import PaydayPolicy
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


async def get_payday_policy(
    db: AsyncSession, branch_id: str | None, rank, as_of: datetime
) -> PaydayPolicy | None:
    """지급일 규칙 — **좁은 쪽이 이긴다** (지점+직급 > 지점 > 직급 > 전사 기본).

    같은 첨단 안에서도 FC 는 말일, 트레이너는 익월 10일이라 지점만으로는 안 갈린다.
    """
    stmt = (
        select(PaydayPolicy)
        .where(
            PaydayPolicy.effective_from <= as_of,
            or_(PaydayPolicy.branch_id == branch_id, PaydayPolicy.branch_id.is_(None)),
            or_(PaydayPolicy.rank == rank, PaydayPolicy.rank.is_(None)),
        )
        .order_by(
            PaydayPolicy.branch_id.isnot(None).desc(),
            PaydayPolicy.rank.isnot(None).desc(),
            PaydayPolicy.effective_from.desc(),
        )
    )
    return (await db.execute(stmt)).scalars().first()


def compute_payday(year_month: str, policy: PaydayPolicy | None = None) -> date:
    """그 명세서의 지급일.

    - 말일형(당월) — 그 달 말일에 준다. 화순 전원·동광주·첨단 FC.
    - 익월 D형 — 그 달 D 일에 준다. 동광주·첨단 트레이너(10일).

    `policy` 가 없으면 예전처럼 말일이다 (규칙이 아직 안 깔린 곳).
    """
    y, m = int(year_month[:4]), int(year_month[5:7])
    if policy is not None and policy.next_month and policy.day:
        return date(y, m, min(policy.day, _last_day(y, m)))
    return date(y, m, _last_day(y, m))


def payroll_window(year_month: str, policy: PaydayPolicy | None = None) -> tuple[datetime, datetime]:
    """그 명세서가 덮는 **근무 기간** `[start, end)` — 달력 월이 아니다.

    - 말일형 — `[그달 1일, 다음달 1일)`. 지급일이 그 주기의 마지막 날이다.
    - 익월 D형 — `[전월 D일, 그달 D일)`. 9/10 에 받는 돈이 8/10~9/9 것이라는 뜻이다.

    점수·랭킹은 이 창을 안 쓴다 (`period_range` 그대로 달력 월). 급여만 옮긴다.
    """
    y, m = int(year_month[:4]), int(year_month[5:7])
    if policy is not None and policy.next_month and policy.day:
        day = policy.day
        prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
        start = datetime(prev_y, prev_m, min(day, _last_day(prev_y, prev_m)), tzinfo=timezone.utc)
        end = datetime(y, m, min(day, _last_day(y, m)), tzinfo=timezone.utc)
        return start, end
    return period_range(year_month)


def payroll_started(year_month: str, policy: PaydayPolicy | None) -> bool:
    """이 달 명세서를 만들어도 되는가 — 주기 시작이 측정 개시일 이후여야 한다.

    앱을 켜기 전 실적까지 급여로 잡으면 **안 준 돈이 생긴 것처럼** 보인다.
    """
    if policy is None:
        return True
    start, _ = payroll_window(year_month, policy)
    return start.date() >= policy.starts_on


def payday_window(year_month: str, today: date, policy: PaydayPolicy | None = None) -> dict:
    """급여 신청 창 — 지급일 당일만 열림(전날까지 막힘)."""
    payday = compute_payday(year_month, policy)
    return {"year_month": year_month, "payday": payday.isoformat(), "is_open": today == payday}


def payroll_month_of(today: date, policy: PaydayPolicy | None = None) -> str:
    """오늘이 속한 **진행 중 주기**의 명세서 월 (YYYY-MM).

    말일형이면 오늘 그 달이고, 익월 D형이면 D 일 전에는 이번 달·이후에는 다음 달이다
    (9/9 는 9월 명세서, 9/10 은 10월 명세서 주기의 첫날).
    """
    y, m = today.year, today.month
    if policy is not None and policy.next_month and policy.day and today.day >= policy.day:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}"


def due_year_month(today: date, policy: PaydayPolicy | None = None) -> str | None:
    """오늘이 지급일인 급여 월(YYYY-MM) — 아니면 None.

    말일형이면 오늘이 말일일 때 그 달, 익월 10일형이면 오늘이 10일일 때 그 달이다.
    지난 달도 후보로 둔다 (규칙이 바뀌는 달에 어느 쪽으로도 걸릴 수 있다)."""
    y, m = today.year, today.month
    prev = f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"
    for cand in (f"{y:04d}-{m:02d}", prev):
        if compute_payday(cand, policy) == today:
            return cand
    return None


def can_adjust_incentive(employee: Employee, policy: RankPolicy | None) -> bool:
    """본인이 PT 커미션을 고쳐서 신청할 수 있는 사람인가.

    자동 집계가 빠뜨린 수업(대타·기록 누락)을 바로잡으라고 연 자리다.
    **알바는 시급제라 커미션이 없고, FC 는 요율이 0** 이라 고칠 것이 없다.
    """
    if employee.employment_type == EmploymentType.PART_TIME:
        return False
    if policy is None:
        return False
    return policy.new_rate > 0 or policy.renewal_rate > 0


def apply_incentive_override(
    data: dict,
    employee: Employee,
    incentive_new: int | None,
    incentive_renewal: int | None,
) -> dict:
    """본인이 고친 커미션을 얹고 총액·공제를 다시 센다.

    `incentive_*_auto` 는 **안 건드린다** — 원래 계산값이 남아야 결재하는 쪽이
    얼마를 고쳤는지 본다. 기본급은 직급 정책에서 나오는 값이라 손대지 않는다.
    """
    if incentive_new is None and incentive_renewal is None:
        return data
    if incentive_new is not None:
        data["incentive_new"] = incentive_new
    if incentive_renewal is not None:
        data["incentive_renewal"] = incentive_renewal
    gross = (
        data["base_salary"]
        + data["incentive_new"]
        + data["incentive_renewal"]
        + data["other_allowances"]
    )
    deductions = _deductions(gross, employee.deduction_method)
    total_deduction = sum(line["amount"] for line in deductions)
    data["gross"] = gross
    data["deductions"] = deductions
    data["total_deduction"] = total_deduction
    data["net"] = gross - total_deduction
    return data


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


async def get_hourly_wage(
    db: AsyncSession, branch_id: str, as_of: datetime
) -> int | None:
    """그 시점에 유효했던 시급 — 지점 우선(지정 > 전사 null), 최신 effective_from.

    **상수로 두지 않는 이유**: 최저임금이 오를 때 값을 바꾸면 지난 달 급여까지
    새 시급으로 다시 계산된다. 기간을 나눠 두면 그달 값이 그대로 남는다.
    """
    stmt = (
        select(HourlyWagePolicy)
        .where(
            HourlyWagePolicy.effective_from <= as_of,
            or_(
                HourlyWagePolicy.branch_id == branch_id,
                HourlyWagePolicy.branch_id.is_(None),
            ),
        )
        .order_by(
            HourlyWagePolicy.branch_id.isnot(None).desc(),
            HourlyWagePolicy.effective_from.desc(),
        )
    )
    policy = (await db.execute(stmt)).scalars().first()
    return policy.wage if policy else None


def _shift_minutes(employee: Employee) -> int:
    """하루 근무 분 — 본인이 온보딩에서 설정한 출퇴근 시각 그대로.

    **휴게시간을 빼지 않는다** (2026-08-05 결정). 설정한 시간을 그대로 준다.
    자정을 넘기는 근무(22:00~06:00)는 하루를 더해 잰다.
    """
    if not employee.shift_start or not employee.shift_end:
        return 0
    start_h, start_m = (int(x) for x in employee.shift_start.split(":"))
    end_h, end_m = (int(x) for x in employee.shift_end.split(":"))
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if end <= start:
        end += 24 * 60
    return end - start


def _work_day_count(employee: Employee, start: datetime, end: datetime) -> int:
    """급여 주기 `[start, end)` 안에 본인 근무 요일이 몇 번 오는가 (work_days 는 ISO 1~7)

    달력 월이 아니라 주기로 센다 — 익월 10일 지점은 8/10~9/9 가 한 달치다.
    """
    if not employee.work_days:
        return 0
    wanted = set(employee.work_days)
    day = start.date()
    last = end.date()
    count = 0
    while day < last:
        if day.isoweekday() in wanted:
            count += 1
        day += timedelta(days=1)
    return count


class NoScheduleError(Exception):
    """근무 시간·요일을 설정 안 한 알바 — 급여를 뽑을 근거가 없다.

    조용히 0원 명세서를 만들면 **안 준 게 아니라 0원을 준 것**이 되어
    나중에 되짚기 어렵다. 지금은 막고 근무 설정을 받게 한다.
    """


async def build_hourly_payslip_data(
    db: AsyncSession,
    employee: Employee,
    year_month: str,
    wage: int,
    payday: PaydayPolicy | None = None,
) -> dict:
    """알바(PART_TIME) 명세서 — **시급만.** 직급 기본급·PT 인센티브가 없다.

    근거는 **본인이 설정한 근무시간**이다 (첫 로그인 온보딩에서 받는 값).
    출퇴근 스캔 실적이 아니라서 스캔을 빼먹어도 급여가 비지 않는다.
    """
    per_day = _shift_minutes(employee)
    win_start, win_end = payroll_window(year_month, payday)
    day_count = _work_day_count(employee, win_start, win_end)
    total_minutes = per_day * day_count
    if total_minutes <= 0:
        raise NoScheduleError
    gross = round(total_minutes / 60 * wage)

    deductions = _deductions(gross, employee.deduction_method)
    total_deduction = sum(line["amount"] for line in deductions)

    return {
        "rank": employee.rank,
        "pay_date": compute_payday(year_month, payday),
        # 알바는 직급 기본급이 없다 — 시급으로 계산한 값이 통째로 기본급 자리에 온다
        "base_salary": gross,
        "incentive_new": 0,
        "incentive_renewal": 0,
        "incentive_new_auto": 0,
        "incentive_renewal_auto": 0,
        "other_allowances": 0,
        "gross": gross,
        "deduction_method": employee.deduction_method,
        "deductions": deductions,
        "total_deduction": total_deduction,
        "net": gross - total_deduction,
        "basis": {
            "new_sales": [],
            "renewal_sales": [],
            "session_signs": 0,
            # 어떻게 이 금액이 나왔는지 — 화면이 그대로 보여줄 수 있게 남긴다
            "hourly": {
                "wage": wage,
                "minutes_per_day": per_day,
                "work_days": day_count,
                "total_minutes": total_minutes,
            },
        },
    }


async def build_payslip_data(
    db: AsyncSession,
    employee: Employee,
    year_month: str,
    policy: RankPolicy,
    payday: PaydayPolicy | None = None,
) -> dict:
    # 달력 월이 아니라 **그 사람의 급여 주기**로 센다 (익월 10일이면 전월10~당월9)
    start, end = payroll_window(year_month, payday)
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
        "pay_date": compute_payday(year_month, payday),
        "base_salary": policy.base_salary,
        "incentive_new": incentive_new,
        "incentive_renewal": incentive_renewal,
        # 신청할 때 본인이 고칠 수 있어서 원래 계산값을 따로 남긴다 (§76)
        "incentive_new_auto": incentive_new,
        "incentive_renewal_auto": incentive_renewal,
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
        # 지급일 규칙이 사람마다 다르다 — 급여 주기와 측정 개시일이 여기서 갈린다
        payday = await get_payday_policy(db, employee.branch_id, employee.rank, start)
        if not payroll_started(year_month, payday):
            continue  # 측정 개시 전 주기 — 앱을 켜기 전 실적은 급여로 안 친다
        if employee.employment_type == EmploymentType.PART_TIME:
            # 알바는 시급제 — 직급 정책을 안 탄다 (PT 인센티브도 없다)
            wage = await get_hourly_wage(db, employee.branch_id, start)
            if wage is None:
                continue  # 시급 정책이 없으면 뽑을 근거가 없다
            try:
                data = await build_hourly_payslip_data(db, employee, year_month, wage, payday)
            except NoScheduleError:
                continue  # 근무 설정 전이면 건너뛴다 (0원 명세서를 만들지 않는다)
        else:
            policy = await get_rank_policy(db, employee.rank, employee.branch_id, start)
            if policy is None:
                continue  # 요율 정책 없는 직급은 건너뜀
            data = await build_payslip_data(db, employee, year_month, policy, payday)
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
