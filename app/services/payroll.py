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
    PayslipStatus,
    ProjectRequestStatus,
    Rank,
    RegistrationType,
    Role,
)
from app.models.scoring.my_task import MyTaskMiss
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.payroll.payslip import Payslip
from app.models.payroll.hourly_wage import HourlyWagePolicy
from app.models.payroll.payday_policy import PaydayPolicy
from app.models.payroll.rank_policy import RankPolicy
from app.models.members.registration import Registration
from app.models.members.session_sign import SessionSign

FREELANCE_RATE = 0.033
# 4대보험 근로자 부담분 근사치 (건강보험 기준 장기요양 별도)
INSURANCE_RATES = (("국민연금", 0.045), ("건강보험", 0.03545), ("고용보험", 0.009))
LONGTERM_CARE_RATE = 0.1295  # 장기요양 = 건강보험료 × 12.95%

# 매출성과(SALES) 점수는 **여기 없다** — 등록권을 만들 때 바로 매긴다
# (`services/registrations.py` 의 `accrue_sales_score`, 2026-08-31 대표 요청).
#
# 예전에는 이 마감이 그 달 매출을 통째로 더해 한 번에 매겼는데, 그러면
# 한 달이 끝나야 점수가 보이고 **급여 개시일 전 주기는 통째로 빠졌다.**


# 직급별 전사 기본 급여 정책 (기본급, 워크인 요율, 재등록/지인소개 요율).
# 개발자·대표(ADMIN)는 PT 급여 대상 아님 → 정책 없음(마감에서 건너뜀).
# FC = 세전 210만 + FC권 매출(별도·미모델링) → PT 세션 커미션 없음(요율 0).
#: 재등록 요율이 유지되는 문턱 — **트레이너만** (2026-08-31 대표 요청)
#:
#: 그 주기의 재등록·지인소개 세션 단가 합이 이 값을 **넘어야** 재등록 요율(50%)
#: 이고, 못 넘으면 워크인 요율(40%)로 내려간다. 300만원 정확히면 '안 넘은'
#: 것이라 40% 다.
#:
#: **커미션이 아니라 단가 합으로 잰다** — 요율을 정하는 값이 요율 결과에
#: 걸리면 앞뒤가 물린다.
#:
#: 달이 바뀌면 저절로 리셋된다. [build_payslip_data] 가 주기마다 그 주기
#: 싸인만 다시 세기 때문에 따로 지울 상태가 없다.
RENEWAL_RATE_THRESHOLD = 3_000_000

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


#: 지점 누락 **날 수** → 점장 기본급에서 뺄 돈 (2026-08-21 대표 결정).
#:
#: 3회부터다 — 두 번까지는 안 깎는다. **5회에서 멈춘다**: 그 뒤로는 아무리
#: 쌓여도 -50만 그대로다.
MANAGER_MISS_CUT = {3: 300_000, 4: 400_000}
MANAGER_MISS_CUT_MAX = 500_000

#: 이 날부터 센다 — 규칙이 없던 때의 누락으로 급여를 깎지 않는다.
#: 확정 누락 판정(`workers/my_task_miss_scan.STARTS_ON`)과 **같은 날**이어야 한다.
MANAGER_MISS_FROM = date(2026, 9, 1)


async def manager_miss_cut(db: AsyncSession, employee: Employee) -> tuple[int, int]:
    """점장 기본급 차감 — `(누락 날 수, 깎을 돈)`.

    **점장(MANAGER)만이다.** 트레이너·FC 는 자기 누락으로 점수(-20)를 잃지
    돈을 잃지 않는다. 관리 책임을 묻는 자리라 관리하는 사람에게만 붙는다.

    ## 무엇을 세나 — **그 지점에서 누락이 있었던 날의 수**

    같은 날 세 사람이 빠뜨려도 1회다 (2026-08-21 결정 — "하루 단위").
    사유가 승인돼 회복된 날(`APPROVED`)은 안 센다.

    ## 달이 바뀌어도 안 되돌린다

    지각 차감(`LATE_PENALTY`)과 같다. 매달 0으로 리셋하면 달마다 첫 세 번이
    공짜라, 늘 놓치는 지점과 처음 놓친 지점이 같은 값을 문다.

    **그래서 한 번 5회를 넘기면 그 뒤로는 매달 -50만이다.** 되돌리는 길은
    사유서 승인뿐이다 (`POST /my-task-misses/{id}/approve`).
    """
    if employee.role != Role.MANAGER or employee.branch_id is None:
        return 0, 0
    days = (
        await db.scalar(
            select(func.count(func.distinct(MyTaskMiss.date))).where(
                MyTaskMiss.branch_id == employee.branch_id,
                MyTaskMiss.date >= MANAGER_MISS_FROM,
                # 회복된 날은 없던 일이다
                MyTaskMiss.excuse_status.is_distinct_from(ProjectRequestStatus.APPROVED),
            )
        )
    ) or 0
    if days < min(MANAGER_MISS_CUT):
        return days, 0
    return days, MANAGER_MISS_CUT.get(days, MANAGER_MISS_CUT_MAX)


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

    # **트레이너만** — 재등록·지인소개 합이 문턱을 못 넘으면 그 달은 워크인
    # 요율로 내려간다 (2026-08-31 대표 요청). 달이 바뀌면 저절로 리셋된다
    # (이 함수가 주기마다 처음부터 다시 세기 때문이다).
    renewal_rate = policy.renewal_rate
    downgraded = (
        employee.rank == Rank.TRAINER
        and renewal_base <= RENEWAL_RATE_THRESHOLD
        and policy.renewal_rate > policy.new_rate
    )
    if downgraded:
        renewal_rate = policy.new_rate

    incentive_new = round(new_base * policy.new_rate)
    incentive_renewal = round(renewal_base * renewal_rate)
    other_allowances = 0
    miss_count, miss_cut = await manager_miss_cut(db, employee)
    base_salary = policy.base_salary - miss_cut
    gross = base_salary + incentive_new + incentive_renewal + other_allowances
    deductions = _deductions(gross, employee.deduction_method)
    total_deduction = sum(line["amount"] for line in deductions)

    return {
        "rank": employee.rank,
        "pay_date": compute_payday(year_month, payday),
        "base_salary": base_salary,
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
            # 재등록이 문턱을 못 넘어 워크인 요율로 내려갔나 — 결재자가
            # 왜 금액이 낮은지 알 수 있어야 한다
            "renewal_downgraded": downgraded,
            "renewal_base": renewal_base,
            "session_signs": len(signs),
            # 왜 기본급이 줄었나 — **화면에 새로 그리지 않는다.** 근거를 남겨
            # 두는 것이 목적이다 (알바 `hourly` 와 같은 취급)
            "task_miss": {
                "days": miss_count,
                "cut": miss_cut,
                "base_before": policy.base_salary,
            },
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

    # **손 안 댄 초안만 갈아끼운다** (2026-08-31).
    #
    # 예전에는 그 달 명세서를 상태를 안 보고 통째로 지웠다. 이 잡이 매월 1일에
    # 도는데 화순은 지급일이 말일이라, **9/30 에 신청·승인·지급까지 끝낸 것을
    # 10/1 에 지우고 미제출로 되돌렸다.** 대표가 확인하고 지급한 기록(`paid_at`)
    # 까지 날아가서, 직원이 다시 신청하면 이미 준 급여가 결재 대기에 또 선다.
    # 개시일 전 달이면 지우기만 하고 안 만들어서 **행이 통째로 사라지기도 했다.**
    #
    # 사람이 손을 댄 뒤에는(제출·승인·반려·지급) 자동 계산이 덮으면 안 된다.
    locked = set(
        (
            await db.execute(
                select(Payslip.employee_id).where(
                    Payslip.year_month == year_month,
                    Payslip.employee_id.in_(employee_ids),
                    Payslip.status != PayslipStatus.DRAFT,
                )
            )
        )
        .scalars()
        .all()
    )
    await db.execute(
        delete(Payslip).where(
            Payslip.year_month == year_month,
            Payslip.employee_id.in_(employee_ids),
            Payslip.status == PayslipStatus.DRAFT,
        )
    )

    generated: list[Payslip] = []
    for employee in employees:
        if employee.id in locked:
            continue  # 이미 신청·결재가 걸린 달 — 자동 계산이 덮지 않는다
        # 지급일 규칙이 사람마다 다르다 — 급여 주기와 측정 개시일이 여기서 갈린다
        payday = await get_payday_policy(db, employee.branch_id, employee.rank, start)
        if not payroll_started(year_month, payday):
            # 측정 개시 전 주기 — 앱을 켜기 전 실적은 급여로 안 친다.
            #
            # **매출 기여 점수(SALES)도 같이 빠진다** (적립이 이 루프 아래에 있다).
            # 곁가지가 아니라 **그렇게 하기로 정한 것이다 (2026-08-06)** —
            # 매출성과 점수는 돈에서 나온 값이라 급여와 같은 날부터 시작한다.
            # 개시 전 매출도 점수로 쌓고 싶어지면 이 적립을 마감 밖으로 빼야 한다.
            #
            # 랭킹의 '매출' 탭은 영향이 없다 — 거기는 점수 원장이 아니라
            # 등록권 결제액을 직접 합산한다 (`ranking_board.py`).
            continue
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
    return generated
