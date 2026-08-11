"""점수 적립 서비스 — 모든 점수는 ScoreEvent 원장 하나로 (CLAUDE.md §4).

commit 은 호출자가 담당 (트랜잭션 경계 유지).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import current_period
from app.enums import Role, ScoreCategory
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.employee import Employee


def scores_apply_to(employee: Employee) -> bool:
    """이 사람에게 점수를 쌓는가 — **대표·관리자는 아니다**

    사람을 손으로 골라 점수를 주는 자리(`POST /scores`·`POST /contributions`)는
    이걸 먼저 보고 **400 으로 막는다.** 그냥 두면 부여는 성공했다고 뜨는데
    점수는 안 쌓이는 반쪽 상태가 된다.
    """
    return employee.role not in (Role.MASTER, Role.ADMIN)


async def accrue_score(
    db: AsyncSession,
    *,
    employee_id: str,
    branch_id: str,
    category: ScoreCategory,
    points: int,
    created_by_id: str | None = None,  # 시스템 발생(웹훅/스케줄러)이면 None
    source_ref_id: str | None = None,
    reason: str | None = None,
    period: str | None = None,
) -> ScoreEvent | None:
    """점수 1건 적립 — **대표·관리자에게는 안 쌓는다** (2026-08-11 대표 결정).

    점수는 직원을 평가하고 줄 세우는 값이다. 대표·관리자는 그걸 매기는 쪽이지
    받는 쪽이 아니라 아예 원장에 안 넣는다 — 랭킹에서만 빼면 기여도 화면에는
    그대로 남아서 반쪽이 된다.

    **여기 한 곳에서 막는다.** 부르는 자리가 열 군데가 넘어서(환경정비·세션 싸인·
    기여·친절·프로젝트 완료·급여 마감) 각자 검사하게 두면 언젠가 하나가 빠진다.

    안 쌓았으면 `None` 을 돌려준다 — 돌려받은 값을 쓰는 곳은 그때 비켜 가면 된다.
    """
    actor = await db.get(Employee, employee_id)
    if actor is not None and not scores_apply_to(actor):
        return None
    event = ScoreEvent(
        employee_id=employee_id,
        branch_id=branch_id,
        category=category,
        points=points,
        reason=reason,
        source_ref_id=source_ref_id,
        period=period or current_period(),
        created_by_id=created_by_id,
    )
    db.add(event)
    return event
