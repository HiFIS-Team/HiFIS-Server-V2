"""급여 신청 리마인더 잡 (CLAUDE.md §9.5).

**하루에 여러 번 돈다** (2026-08-31 대표 요청).

| 언제 | 누구에게 | 간격 |
|---|---|---|
| 지급일 **전날** | 대상자 전원 | **6시간마다** — 09 · 15 · 21시 |
| 지급일 **당일** | **아직 안 낸 사람만** | **3시간마다** — 09 · 12 · 15 · 18 · 21시 |

**새벽에는 안 보낸다.** 09~21시로 묶었다 — 3시간마다를 하루 전체로 돌리면
새벽 3시에 폰이 울린다. 요청한 간격은 깨어 있는 시간 안에서 지킨다.

**알림함에는 하루 한 줄만 남긴다.** 첫 번째(09시)만 알림함에 쌓고 나머지는
푸시만 보낸다 — 다섯 줄이 쌓이면 알림함이 급여로 도배된다
(프로젝트 마감 리마인더가 같은 이유로 푸시만 보낸다).

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
from app.services.notifications import notify, send_push
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


#: 알림을 보내는 시각 (KST) — 3시간마다, 새벽은 뺀다
REMIND_HOURS = (9, 12, 15, 18, 21)

#: 그중 **전날 예고**를 보내는 시각 — 6시간마다
AHEAD_HOURS = (9, 15, 21)

#: 알림함에 한 줄 남기는 시각 — 나머지는 푸시만
INBOX_HOUR = 9


async def payday_reminders(
    today: date | None = None, hour: int | None = None
) -> None:
    """지급일 전날·당일 리마인더 — 3시간마다 돌면서 보낼 사람을 고른다.

    [today]·[hour] 는 검사용이다. 안 주면 지금 KST 를 쓴다.
    """
    now = now_kst()
    today = today or now.date()
    hour = now.hour if hour is None else hour
    if hour not in REMIND_HOURS:
        return

    async with SessionLocal() as db:
        await ensure_rank_policies(db)
        # 오늘이 지급일 — **아직 안 낸 사람만**
        for emp, year_month in await _targets(db, today):
            if await _submitted(db, emp.id, year_month):
                continue
            await _send(db, hour, emp.id, ntext.payday_today(year_month))
        # 내일이 지급일 — 예고는 6시간마다
        if hour in AHEAD_HOURS:
            for emp, year_month in await _targets(db, today + timedelta(days=1)):
                await _send(db, hour, emp.id, ntext.payday_tomorrow(year_month))
        await db.commit()


async def _send(db, hour: int, employee_id: str, text: dict) -> None:
    """첫 번째만 알림함에 남기고 나머지는 푸시만 — 알림함이 급여로 안 덮이게."""
    if hour == INBOX_HOUR:
        await notify(db, employee_id=employee_id, **text)
    else:
        await send_push(db, employee_id=employee_id, **text)
