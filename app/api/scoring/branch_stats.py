"""지점 매출 숫자 통계 — 점장이 개인 업무로 적어 내는 누적 숫자 (2026-09-30 대표 요청).

화순 점장은 매일 개인 업무 `기존·신규·일권 체크` 를 체크하면서 숫자 칸에
**이번 달 들어 지금까지의 누적**을 적는다 (9/11 기존 38 → 9/30 기존 94).
이걸 날·주·달로, 그리고 **지난달 같은 날과 견주어** 보는 화면의 재료다.

**권한을 안 가린다** — 전 직원이 본다. 다만 MEMBER·MANAGER 는 자기 지점 것만,
MASTER·ADMIN 은 지점을 골라 본다.

**칸 이름을 다듬어 합친다.** 예전 업무는 칸 이름에 숫자가 섞여 있었다
(`기존38`·`일권10명`). 숫자·`명`·공백을 떼면 같은 칸이 된다.
"""

import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.periods import KST
from app.db.session import get_db
from app.enums import Role
from app.models.scoring.my_task import MyTask, MyTaskCheck
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel

router = APIRouter(prefix="/branch-stats", tags=["branch-stats"])


class StatDayOut(CamelModel):
    date: date
    #: 그날 적은 누적 숫자 — `{"기존": 94, "신규": 41, "일권": 36}`
    values: dict[str, float]


class BranchStatsOut(CamelModel):
    branch_id: str | None
    #: 칸 이름 — 처음 나온 차례대로
    fields: list[str]
    days: list[StatDayOut]


def clean_name(name: str) -> str:
    """`기존38` · `일권10명` · ` 신규 ` → `기존` · `일권` · `신규`"""
    cleaned = re.sub(r"[\d\s명]+", "", name or "")
    return cleaned or (name or "").strip()


@router.get("", response_model=BranchStatsOut)
async def branch_stats(
    branch_id: str | None = Query(None, alias="branchId"),
    months: int = Query(13, ge=1, le=36),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchStatsOut:
    # 직원·점장은 **자기 지점으로 고정** — 남의 지점을 넣어도 무시한다
    if current.role not in (Role.MASTER, Role.ADMIN) or not branch_id:
        branch_id = current.branch_id
    today = datetime.now(timezone.utc).astimezone(KST).date()
    since = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)

    rows = await db.execute(
        select(MyTaskCheck.date, MyTaskCheck.values)
        .join(MyTask, MyTask.id == MyTaskCheck.my_task_id)
        .join(Employee, Employee.id == MyTask.employee_id)
        .where(
            Employee.branch_id == branch_id,
            Employee.role == Role.MANAGER,
            MyTaskCheck.date >= since,
        )
        .order_by(MyTaskCheck.date)
    )
    fields: list[str] = []
    by_day: dict[date, dict[str, float]] = {}
    for day, values in rows:
        for key, raw in (values or {}).items():
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            name = clean_name(key)
            if name not in fields:
                fields.append(name)
            slot = by_day.setdefault(day, {})
            # 같은 날 두 업무가 같은 칸을 적었으면 **큰 쪽**(더 늦게 센 누적)
            slot[name] = max(slot.get(name, raw), raw)
    return BranchStatsOut(
        branch_id=branch_id,
        fields=fields,
        days=[StatDayOut(date=d, values=v) for d, v in sorted(by_day.items())],
    )
