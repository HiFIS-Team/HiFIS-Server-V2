"""직원 식별자 발급 — 스캐너용 바코드 + 사람이 읽는 사번 (CLAUDE.md §6.9, §2.2).

- barcode: 지점 스캐너가 읽는 8자리 기계 코드.
- emp_no: 프로필 표시용 사번 {입사연도}-{4자리 순번}.
둘 다 중복 없는 값 발급. commit 은 호출자.
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org.employee import Employee


async def unique_barcode(db: AsyncSession) -> str:
    """중복 없는 8자리 숫자 바코드(10000000~99999999) 발급."""
    for _ in range(20):
        code = str(secrets.randbelow(90_000_000) + 10_000_000)
        if await db.scalar(select(Employee.id).where(Employee.barcode == code)) is None:
            return code
    raise RuntimeError("바코드 발급 실패 — 충돌 과다")


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
