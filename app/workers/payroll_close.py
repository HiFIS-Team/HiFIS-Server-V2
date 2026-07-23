"""급여 월마감 잡 — 매월 전월 명세서 생성 (CLAUDE.md §9.5)."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.org.branch import Branch
from app.services.payroll import generate_branch_payslips


def previous_month() -> str:
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


async def close_previous_month() -> None:
    """전월 급여를 전 지점 마감(명세서 + SALES 자동 기여도)."""
    year_month = previous_month()
    async with SessionLocal() as db:
        branches = (await db.execute(select(Branch))).scalars().all()
        for branch in branches:
            await generate_branch_payslips(db, branch.id, year_month)
        await db.commit()
