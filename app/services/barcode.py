"""직원 출근 바코드 발급 — 스캐너용 고유 코드 (CLAUDE.md §6.9).

지점 바코드 스캐너가 읽는 값 = 직원 고유 8자리 코드(사번/뱃지).
중복 없는 값을 발급(충돌 시 재시도). commit 은 호출자.
"""

import secrets

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
