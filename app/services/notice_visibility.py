from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff.branch import Branch
from app.models.staff.employee import Employee

_BLOCKED_BRANCH_NAME = "동광주"


async def is_notice_blocked(
    db: AsyncSession, employee: Employee
) -> bool:
    """동광주점 소속 직원의 공지 노출 여부를 판정한다."""
    if not employee.branch_id:
        return False
    branch = await db.get(Branch, employee.branch_id)
    return branch is not None and branch.name == _BLOCKED_BRANCH_NAME
