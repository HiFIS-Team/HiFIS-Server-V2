"""지점 묶음 가시성 — 프로젝트·회의록을 서로 보여 줄 범위 (2026-08-19).

`첨단`·`화순` 은 서로 보고 `동광주` 는 단독이다. 묶음은 코드가 아니라
`Branch.share_group` 에 들어 있다 — 지점이 늘거나 묶음이 바뀌어도 값만 고치면
되고 배포가 필요 없다.

**`share_group` 이 `NULL` 이면 전 지점**이다.

| | 뜻 |
|---|---|
| 보는 사람의 지점이 NULL (본사) | 전부 본다 |
| 대상의 지점이 NULL (본사가 만든 것·옛 행) | 모두에게 보인다 |

**담당자·작성자·참석자는 지점과 무관하게 본다.** 그건 여기서 다루지 않고
부르는 쪽에서 `or_` 로 얹는다 — 안 그러면 다른 지점 프로젝트에 담당으로
지정된 사람이 **자기 일을 목록에서 못 본다.**
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Role
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee


async def visible_branch_ids(db: AsyncSession, current: Employee) -> list[str] | None:
    """`current` 가 지점 기준으로 볼 수 있는 지점 id 들.

    `None` 은 **제한 없음**이다 (MASTER·ADMIN, 그리고 본사 소속).
    """
    if current.role in (Role.MASTER, Role.ADMIN):
        return None

    my_group: str | None = None
    if current.branch_id:
        my_group = await db.scalar(select(Branch.share_group).where(Branch.id == current.branch_id))

    # 본사 소속이거나 묶음이 안 정해진 지점 — 가를 근거가 없으므로 막지 않는다.
    # 막는 쪽으로 두면 묶음을 넣기 전에 화면이 통째로 비어 고장으로 보인다.
    if my_group is None:
        return None

    rows = await db.scalars(
        select(Branch.id).where(
            or_(Branch.share_group.is_(None), Branch.share_group == my_group)
        )
    )
    return list(rows)
