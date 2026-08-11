"""랭킹 계산 서비스 — /scores/ranking 과 랭킹 알림 잡의 공통 소스 (CLAUDE.md §4.1).

kind(랭킹 탭) → ScoreEvent 필터. OVERALL=전체 합, SALES=CONTRIB 중 sales:* 만.
compute_ranking 은 ScoreEvent 합산으로 (employee_id, name, points, rank) 리스트를 만든다.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import RankingKind, Role, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.score_event import ScoreEvent

# 표시 순서: 종합 → 매출 → 수업 → 친절 → 피드백
RANKING_KINDS = [
    RankingKind.OVERALL,
    RankingKind.SALES,
    RankingKind.CLASS,
    RankingKind.KINDNESS,
    RankingKind.PEER,
]
KIND_LABEL = {
    RankingKind.OVERALL: "종합왕",
    RankingKind.SALES: "매출왕",
    RankingKind.CLASS: "수업왕",
    RankingKind.KINDNESS: "친절왕",
    RankingKind.PEER: "피드백왕",
    RankingKind.PROJECT: "프로젝트왕",
    RankingKind.ENV: "환경왕",
}


def kind_conditions(kind: RankingKind) -> list:
    """RankingKind → ScoreEvent 필터 조건 목록. OVERALL=[](전체), SALES=CONTRIB 중 sales:*."""
    if kind == RankingKind.SALES:
        return [
            ScoreEvent.category == ScoreCategory.CONTRIB,
            ScoreEvent.source_ref_id.like("sales:%"),
        ]
    if kind == RankingKind.OVERALL:
        return []
    return [ScoreEvent.category == ScoreCategory(kind.value)]


async def compute_ranking(
    db: AsyncSession,
    *,
    kind: RankingKind | None = None,
    category: ScoreCategory | None = None,
    period: str | None = None,
    branch_id: str | None = None,
) -> list[dict]:
    """[{employee_id, name, points, rank}] — points 내림차순, rank 는 1부터.

    **대표·관리자는 빼고 센다** (2026-08-11 대표 결정). 줄 세우는 쪽이지 서는
    쪽이 아니다 — 근태 판정에서 뺀 것과 같은 이유다 (backend-gap 70번).
    점수 원장에는 그대로 쌓인다. 등수만 안 매긴다.

    **`GET /scores/ranking` 도 이 함수를 쓴다.** 예전에는 라우터가 같은 질의를
    한 벌 더 갖고 있어서, 여기만 고쳤더니 화면에는 그대로 떴다 (실제로 겪었다).

    [kind] 가 [category] 보다 우선한다 — 랭킹 탭이 곧 kind 다.
    """
    total = func.coalesce(func.sum(ScoreEvent.points), 0).label("points")
    stmt = (
        select(Employee.id, Employee.name, total)
        .join(ScoreEvent, ScoreEvent.employee_id == Employee.id)
        .where(Employee.role.notin_([Role.MASTER, Role.ADMIN]))
    )
    if kind is not None:
        for cond in kind_conditions(kind):
            stmt = stmt.where(cond)
    elif category is not None:
        stmt = stmt.where(ScoreEvent.category == category)
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    if branch_id:
        stmt = stmt.where(ScoreEvent.branch_id == branch_id)
    stmt = stmt.group_by(Employee.id, Employee.name).order_by(total.desc())
    rows = (await db.execute(stmt)).all()
    return [
        {"employee_id": r.id, "name": r.name, "points": r.points, "rank": i + 1}
        for i, r in enumerate(rows)
    ]
