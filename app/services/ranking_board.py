"""랭킹판 집계 — 앱 랭킹 화면이 사람마다 보여주는 값들 (CLAUDE.md §4.1).

`/scores/ranking` 은 kind 별 **점수 합**만 준다. 앱 랭킹 화면은 그것 말고도
"신규 3 · 재등록 5", "리뷰 27건 · ★4.5", "3 / 4건", "이번 달 54회" 같은
**근거 한 줄**을 같이 보여준다. 그 값들이 서로 다른 테이블에 있어서 여기서 모은다.

한 달치를 한 번에 모아 사람별로 접어 준다 — 사람마다 쿼리를 날리면
인원수만큼 요청이 늘어난다.
"""

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import period_range
from app.enums import RegistrationType, ScoreCategory
from app.models.members.registration import Registration
from app.models.projects.project import Project
from app.models.scoring.env import EnvTaskLog
from app.models.scoring.kindness import KindnessSurvey
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.employee import Employee

# 앱 랭킹 탭 순서 — 종합은 나머지 넷을 환산해 평균 내므로 맨 뒤다
METRICS = ["revenue", "kindness", "project", "care", "overall"]


def _blank(employee: Employee) -> dict:
    return {
        "employeeId": employee.id,
        "name": employee.name,
        "branchId": employee.branch_id,
        "revenue": 0,
        "newSignups": 0,
        "reSignups": 0,
        "kindness": 0,
        "reviews": 0,
        "stars": 0.0,
        "projectDone": 0,
        "projectTotal": 0,
        "care": 0,
        "lastRank": [0, 0, 0, 0, 0],
    }


async def build_board(
    db: AsyncSession, *, period: str, branch_id: str | None = None
) -> list[dict]:
    """한 달치 랭킹판. 순위는 매기지 않고 **값만** 채운다."""
    start, end = period_range(period)

    people = (
        await db.scalars(
            select(Employee).where(Employee.deleted_at.is_(None))
        )
    ).all()
    if branch_id:
        people = [p for p in people if p.branch_id == branch_id]
    board = {p.id: _blank(p) for p in people}

    # 매출 — 그 달에 등록된 등록권의 결제액. 신규/재등록을 따로 센다
    rows = (
        await db.execute(
            select(
                Registration.trainer_id,
                Registration.type,
                func.coalesce(func.sum(Registration.price_paid), 0),
                func.count(),
            )
            .where(Registration.created_at >= start, Registration.created_at < end)
            .group_by(Registration.trainer_id, Registration.type)
        )
    ).all()
    for trainer_id, kind, paid, count in rows:
        row = board.get(trainer_id)
        if row is None:
            continue
        row["revenue"] += int(paid or 0)
        if kind == RegistrationType.NEW:
            row["newSignups"] += count
        else:
            row["reSignups"] += count

    # 친절 점수 — 점수는 원장(ScoreEvent)에서, 리뷰 수·별점은 설문에서
    rows = (
        await db.execute(
            select(ScoreEvent.employee_id, func.coalesce(func.sum(ScoreEvent.points), 0))
            .where(
                ScoreEvent.category == ScoreCategory.KINDNESS,
                ScoreEvent.period == period,
            )
            .group_by(ScoreEvent.employee_id)
        )
    ).all()
    for employee_id, points in rows:
        if employee_id in board:
            board[employee_id]["kindness"] = int(points or 0)

    rows = (
        await db.execute(
            select(
                KindnessSurvey.praised_employee_id,
                func.count(),
                func.coalesce(func.avg(cast(KindnessSurvey.stars, Float)), 0.0),
            )
            .where(
                KindnessSurvey.submitted_at >= start,
                KindnessSurvey.submitted_at < end,
            )
            .group_by(KindnessSurvey.praised_employee_id)
        )
    ).all()
    for employee_id, count, stars in rows:
        row = board.get(employee_id)
        if row is None:
            continue
        row["reviews"] = count
        row["stars"] = round(float(stars or 0), 1)

    # 환경정비 — 그 달 수행 횟수
    rows = (
        await db.execute(
            select(EnvTaskLog.employee_id, func.count())
            .where(EnvTaskLog.created_at >= start, EnvTaskLog.created_at < end)
            .group_by(EnvTaskLog.employee_id)
        )
    ).all()
    for employee_id, count in rows:
        if employee_id in board:
            board[employee_id]["care"] = count

    # 프로젝트 — 그 달 안에 기한이 있는 것 중 내가 담당인 것.
    # `assignee_ids` 가 JSONB 배열이라 파이썬에서 접는다 (프로젝트 수가 적다).
    projects = (
        await db.scalars(
            select(Project).where(Project.due >= start, Project.due < end)
        )
    ).all()
    for project in projects:
        for employee_id in project.assignee_ids or []:
            row = board.get(employee_id)
            if row is None:
                continue
            row["projectTotal"] += 1
            if (project.progress or 0) >= 100:
                row["projectDone"] += 1

    return list(board.values())


def _value(row: dict, metric: str, pool: list[dict]) -> float:
    """항목별 값 — 앱의 `_valueOf` 와 같은 계산이다."""
    if metric == "revenue":
        return float(row["revenue"])
    if metric == "kindness":
        return float(row["kindness"])
    if metric == "project":
        total = row["projectTotal"]
        return 0.0 if total == 0 else row["projectDone"] * 100 / total
    if metric == "care":
        return float(row["care"])
    # 종합 — 항목마다 1등을 100점으로 두고 상대 위치를 평균 낸다.
    # 매출은 원, 환경정비는 횟수라 단위가 달라서 그냥 더할 수 없다.
    total = 0.0
    parts = METRICS[:-1]
    for part in parts:
        top = max((_value(other, part, pool) for other in pool), default=0.0)
        if top > 0:
            total += _value(row, part, pool) / top * 100
    return total / len(parts)


def rank_board(board: list[dict]) -> dict[str, list[int]]:
    """사람별 항목 순위 — `{employeeId: [매출, 친절, 프로젝트, 환경, 종합]}`.

    값이 0 이면 순위를 안 준다(0). 아무것도 안 한 달에 등수가 붙으면
    '지난달 3위' 같은 표시가 뜻을 잃는다.
    """
    ranks: dict[str, list[int]] = {row["employeeId"]: [0] * len(METRICS) for row in board}
    for at, metric in enumerate(METRICS):
        ordered = sorted(board, key=lambda r: _value(r, metric, board), reverse=True)
        place = 0
        for row in ordered:
            if _value(row, metric, board) <= 0:
                continue
            place += 1
            ranks[row["employeeId"]][at] = place
    return ranks
