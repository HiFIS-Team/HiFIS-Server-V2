"""직원 사번 발급 — 사람이 읽는 식별자 (CLAUDE.md §2.2).

emp_no: {입사연도}-{4자리 순번}. 프로필 표시 + 출근 스캔(홈 바코드로 렌더)에 공용.
중복 없는 값 발급. commit 은 호출자.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org.employee import Employee


async def unique_emp_no(db: AsyncSession) -> str:
    """사번 {입사연도}-{4자리 순번} 발급 — 해당 연도 최대 순번 +1."""
    prefix = f"{datetime.now(timezone.utc).year}-"
    last = await db.scalar(
        select(Employee.emp_no)
        .where(Employee.emp_no.like(f"{prefix}%"))
        .order_by(Employee.emp_no.desc())
        .limit(1)
    )
    seq = int(last.split("-")[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"
