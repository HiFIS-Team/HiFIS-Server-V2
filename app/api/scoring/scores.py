"""Score 라우터 — 원장 조회 · 랭킹 · 요약 · 운영자 부여 (CLAUDE.md §4.1).

랭킹/진급 합산은 ScoreEvent 원장 하나에서 집계. period 는 저장 문자열("2026-07") 정확 일치.
랭킹/목록은 지점 스코프(§0): MEMBER=본인 지점 / MANAGER·ADMIN=전체.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.core.periods import current_period
from app.db.session import get_db
from app.enums import RankingKind, Role, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.my_task import MyTaskMiss
from app.models.scoring.rank_overtake import RankOvertake
from app.models.scoring.score_event import ScoreEvent
from app.schemas.scoring.score import (
    RankingBoardItem,
    RankOvertakeOut,
    RankingItem,
    ScoreCreate,
    ScoreEventOut,
    ScoreSummary,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.ranking import compute_ranking
from app.services.ranking_board import METRICS, build_board, rank_board
from app.services.scoring import accrue_score, scores_apply_to

router = APIRouter(prefix="/scores", tags=["scores"], dependencies=[Depends(get_current_user)])


#: 동료평가 점수는 **평가받은 사람에게 안 보인다** (2026-08-31 대표 지시).
#:
#: 익명이 이 기능의 전제다. 평가 내용(`/peer-reviews`)은 원래 본인이 쓴 것만
#: 보이는데, **점수 원장이 그 구멍이었다** — 자기 PEER 줄을 조회하면 몇 명이
#: 평가했는지, 각각 몇 점을 줬는지가 그대로 나왔다 (평가자 이름까지 나오던
#: 것은 `peer_reviews.py` 에서 따로 막았다).
#:
#: 그래서 MEMBER·MANAGER 에게는 **PEER 가 아예 없는 값**이다 — 목록에서 빠지고
#: 요약의 칸과 합계에서도 빠진다. 볼 수 있는 것은 MASTER·ADMIN 뿐이다.
#:
#: ⚠️ **종합 랭킹에는 여전히 섞여 있다.** 종합은 원장 전체 합이라 PEER 가
#: 들어간다 — 다만 항목이 안 갈려서 어느 만큼이 동료평가인지는 알 수 없다.
#: 거기서까지 빼려면 점수 체계를 바꿔야 해서 그대로 뒀다.
def _hides_peer(role: Role) -> bool:
    return role in (Role.MEMBER, Role.MANAGER)


@router.get("", response_model=list[ScoreEventOut])
async def list_scores(
    db: AsyncSession = Depends(get_db),
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    category: ScoreCategory | None = Query(None),
    period: str | None = Query(None),
    # 깎인 것만 — **차감을 볼 자리가 아무 데도 없었다** (2026-08-28 대표 요청).
    #
    # 지각(`LATE`)·업무 누락(`TASK_MISS`)은 랭킹 어느 탭에도 안 서고 종합
    # 점수만 조용히 깎았다. 센터 기여도 화면에 `+` 와 같이 세우려는데,
    # 카테고리를 안 걸고 다 받으면 **환경정비·수업까지 통째로** 온다
    # (한 사람 한 달에 수백 줄, 대표는 전 직원치라 수천 줄).
    #
    # 카테고리를 여럿 부르는 대신 여기서 부호로 자른다 — 프로젝트 평가나
    # 운영자 감점처럼 **음수가 될 수 있는 나머지도 같이** 걸린다.
    negative_only: bool = Query(False, alias="negativeOnly"),
) -> list[ScoreEvent]:
    stmt = select(ScoreEvent)
    # 동료평가는 평가받은 사람에게 안 보인다 ([_hides_peer]) — 종류를 콕 집어
    # 물어도 빈 목록이 온다 (403 을 주면 '있긴 있다'는 게 드러난다)
    if _hides_peer(current.role):
        stmt = stmt.where(ScoreEvent.category != ScoreCategory.PEER)
    if scope:
        stmt = stmt.where(ScoreEvent.branch_id == scope)
    if employee_id:
        stmt = stmt.where(ScoreEvent.employee_id == employee_id)
    if category:
        stmt = stmt.where(ScoreEvent.category == category)
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    if negative_only:
        stmt = stmt.where(ScoreEvent.points < 0)
    result = await db.execute(stmt.order_by(ScoreEvent.created_at.desc()))
    return list(result.scalars().all())


@router.get("/ranking", response_model=list[RankingItem])
async def ranking(
    db: AsyncSession = Depends(get_db),
    current: Employee = Depends(get_current_user),
    kind: RankingKind | None = Query(None),
    category: ScoreCategory | None = Query(None),
    period: str | None = Query(None),
    branch_id: str | None = Query(None, alias="branchId"),
) -> list[RankingItem]:
    # 피드백왕(PEER)은 동료평가 총점 줄세우기다 — 누가 몇 점 받았는지가 그대로
    # 드러나서 MASTER·ADMIN 만 본다. 앱 랭킹 탭에는 원래 없는 항목이다
    if (kind is RankingKind.PEER or category is ScoreCategory.PEER) and _hides_peer(current.role):
        raise HTTPException(
            403, detail={"code": "FORBIDDEN", "message": "동료평가 랭킹은 볼 수 없습니다"}
        )
    # 랭킹은 '전사 통합'(전 지점) — 전 인원을 한 줄로 세운다(멤버·매니저 모두 동일한 통합 랭킹).
    # 특정 지점 랭킹만 보려면 branchId 로 필터. (지점 스코프를 걸지 않는 이유: §branch_scope 주석)
    #
    # **질의를 여기서 다시 짜지 않는다.** 예전에는 `compute_ranking` 과 똑같은 것을
    # 한 벌씩 갖고 있어서, 대표·관리자를 빼는 규칙을 저쪽에만 넣었더니 화면에는
    # 그대로 떴다 (실제로 겪었다). 세는 곳은 한 군데다.
    #
    # kind(랭킹 탭)가 category 보다 우선. OVERALL=필터 없음, SALES=CONTRIB 중 sales:* 만.
    rows = await compute_ranking(
        db, kind=kind, category=category, period=period, branch_id=branch_id
    )
    return [
        RankingItem(
            rank=row["rank"],
            employee_id=row["employee_id"],
            name=row["name"],
            points=row["points"],
        )
        for row in rows
    ]


@router.get("/ranking/board", response_model=list[RankingBoardItem])
async def ranking_board(
    db: AsyncSession = Depends(get_db),
    period: str | None = Query(None, description="YYYY-MM (없으면 이번 달)"),
    branch_id: str | None = Query(None, alias="branchId"),
) -> list[RankingBoardItem]:
    """랭킹 화면 한 판 — 사람마다 항목별 값과 **지난달 순위**를 같이 준다.

    `/scores/ranking` 은 kind 별 점수 합만 주는데, 앱 화면은 "신규 3 · 재등록 5"
    같은 근거 줄과 지난달 대비 변동을 같이 보여준다. 그 값들이 등록권·설문·
    환경정비·프로젝트에 흩어져 있어 여기서 한 번에 모은다.

    순위는 **앱이 매긴다** — 지점 필터를 바꿀 때마다 다시 요청하지 않게.
    """
    period = period or current_period()
    board = await build_board(db, period=period, branch_id=branch_id)

    # 지난달 순위 — 같은 방식으로 지난달 판을 만들어 등수만 뽑는다
    year, month = (int(x) for x in period.split("-"))
    before = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    last = await build_board(db, period=before, branch_id=branch_id)
    ranks = rank_board(last)
    for row in board:
        row["lastRank"] = ranks.get(row["employeeId"], [0] * len(METRICS))

    return [RankingBoardItem.model_validate(row) for row in board]


@router.get("/summary", response_model=ScoreSummary)
async def summary(
    employee_id: str = Query(..., alias="employeeId"),
    period: str | None = Query(None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScoreSummary:
    if current.role == Role.MEMBER and employee_id != current.id:  # 멤버는 본인 요약만
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 점수만 조회할 수 있습니다"})
    stmt = select(ScoreEvent.category, func.coalesce(func.sum(ScoreEvent.points), 0)).where(
        ScoreEvent.employee_id == employee_id
    )
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    stmt = stmt.group_by(ScoreEvent.category)
    rows = (await db.execute(stmt)).all()

    by_category = {category.value: 0 for category in ScoreCategory}
    for category, points in rows:
        by_category[str(category)] = points
    # 칸만 지우면 **합계에서 빼서 되짚을 수 있다** — 둘 다 뺀다
    if _hides_peer(current.role):
        by_category.pop(ScoreCategory.PEER.value, None)
    return ScoreSummary(
        employee_id=employee_id,
        period=period,
        total=sum(by_category.values()),
        by_category=by_category,
    )


@router.post("", response_model=ScoreEventOut, status_code=201)
async def create_score(
    payload: ScoreCreate,
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ScoreEvent:
    employee = await db.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원이 존재하지 않습니다"})
    if not scores_apply_to(employee):
        raise HTTPException(
            400,
            detail={"code": "NO_SCORE_TARGET", "message": "대표·관리자에게는 점수를 매기지 않습니다"},
        )
    event = await accrue_score(
        db,
        employee_id=employee.id,
        branch_id=employee.branch_id,
        category=payload.category,
        points=payload.points,
        created_by_id=current.id,
        reason=payload.reason,
        period=payload.period,
    )
    await db.commit()
    await db.refresh(event)
    return event


@router.delete("/{score_id}", status_code=204)
async def revert_score(
    score_id: str,
    # **MASTER 만이다.** 깎은 것을 없던 일로 하는 자리라, 프로젝트 점수 부여·
    # 사유서 승인과 같은 종류다 — 판단하는 한 사람이 한다.
    current: Employee = Depends(require_role(Role.MASTER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """깎인 점수 되돌리기 — **음수 줄만 지운다** (2026-08-28 대표 요청).

    지각·업무 누락은 자동으로 깎이는데, 사정이 있어 봐줘야 할 때 손댈 자리가
    없었다. 사유서(누락)는 승인 경로가 있지만 지각에는 그것도 없다.

    **상쇄로 `+20` 을 한 줄 넣지 않고 줄을 지운다.** 원장 합은 같지만 랭킹
    내역에 `지각 -10` 과 `지각 +10` 이 나란히 서서 무슨 일인지 알 수 없다
    (사유서 승인이 같은 이유로 그렇게 한다).

    지웠다는 사실은 **활동 기록**(`audit_logs`)에 남는다 — 누가 언제 어느
    줄을 되돌렸는지가 거기 있다.

    **양수는 못 지운다.** 여기로 열어 두면 남이 쌓은 점수를 지우는 길이 된다.
    환경정비·기여처럼 원본이 있는 점수는 그 원본을 지우는 자기 경로가 있다.
    """
    event = await db.get(ScoreEvent, score_id)
    if event is None:
        raise HTTPException(404, detail={"code": "SCORE_NOT_FOUND", "message": "점수 기록을 찾을 수 없습니다"})
    if event.points >= 0:
        raise HTTPException(
            400,
            detail={"code": "NOT_A_PENALTY", "message": "깎인 점수만 되돌릴 수 있습니다"},
        )

    # 누락 기록이 이 줄을 가리키고 있으면 끊는다 — 안 끊으면 나중에 사유서를
    # 승인할 때 이미 없는 줄을 지우려 든다 (그쪽은 None 을 견디지만, 남은 id 가
    # '아직 깎여 있다'는 뜻으로 읽힌다)
    miss = await db.scalar(select(MyTaskMiss).where(MyTaskMiss.score_event_id == event.id))
    if miss is not None:
        miss.score_event_id = None

    employee_id, points, reason = event.employee_id, event.points, event.reason
    await db.delete(event)
    # 깎였다고 알림을 받은 사람이라 되돌린 것도 알려야 한다
    await notify(db, employee_id=employee_id, **ntext.score_reverted(points, reason))
    await db.commit()
    return None


@router.get(
    "/overtakes",
    response_model=list[RankOvertakeOut],
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_overtakes(
    db: AsyncSession = Depends(get_db),
    period: str | None = Query(None, description="YYYY-MM (없으면 이번 달)"),
    metric: str | None = Query(None, description="revenue·kindness·project·care·lesson·overall"),
    limit: int = Query(20, ge=1, le=100),
) -> list[RankOvertakeOut]:
    """누가 누구를 무슨 차이로 앞질렀나 — 최근 것부터.

    5분마다 도는 `board_overtake_scan` 이 채운다. 랭킹은 볼 때마다 다시
    계산하는 값이라 서버가 찍어 두지 않으면 '언제 바뀌었나'를 알 수 없다.

    **`GET /scores/ranking/board` 와 같은 판을 본다** — 화면에 뜬 등수와
    어긋나면 "추월했다는데 순위는 그대로"가 된다.
    """
    if metric is not None and metric not in METRICS:
        raise HTTPException(
            400, detail={"code": "BAD_METRIC", "message": "없는 항목이에요"}
        )

    mover = aliased(Employee)
    passed = aliased(Employee)
    stmt = (
        select(RankOvertake, mover, passed)
        .join(mover, mover.id == RankOvertake.mover_id)
        .join(passed, passed.id == RankOvertake.passed_id)
        .where(RankOvertake.period == (period or current_period()))
    )
    if metric:
        stmt = stmt.where(RankOvertake.metric == metric)
    stmt = stmt.order_by(RankOvertake.created_at.desc()).limit(limit)

    return [
        RankOvertakeOut(
            id=row.id,
            period=row.period,
            metric=row.metric,
            mover_id=row.mover_id,
            mover_name=m.name,
            mover_branch_id=m.branch_id,
            passed_id=row.passed_id,
            passed_name=p.name,
            gap=row.gap,
            rank=row.rank,
            created_at=row.created_at,
        )
        for row, m, p in (await db.execute(stmt)).all()
    ]
