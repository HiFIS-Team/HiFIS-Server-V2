"""랭킹판 집계 — 앱 랭킹 화면이 사람마다 보여주는 값들 (CLAUDE.md §4.1).

`/scores/ranking` 은 kind 별 **점수 합**만 준다. 앱 랭킹 화면은 그것 말고도
"신규 3 · 재등록 5", "리뷰 27건 · ★4.5", "3 / 4건", "이번 달 22회" 같은
**근거 한 줄**을 같이 보여준다. 그 값들이 서로 다른 테이블에 있어서 여기서 모은다.

항목마다 화면에 찍히는 단위가 다르다 — 매출은 **금액**, 수업은 **개수**,
나머지는 **점수 원장 합**이다. 원장을 그대로 쓰는 항목(친절·프로젝트·환경정비)은
업무 화면이 쌓아 올린 점수와 랭킹이 어긋나지 않는다.

한 달치를 한 번에 모아 사람별로 접어 준다 — 사람마다 쿼리를 날리면
인원수만큼 요청이 늘어난다.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import period_range
from app.enums import RegistrationType, ScoreCategory
from app.models.members.registration import Registration
from app.models.members.session_sign import SessionSign
from app.models.projects.project import Project
from app.models.scoring.env import EnvTaskLog
from app.models.scoring.kindness import KindnessSurvey
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.employee import Employee

# 앱 랭킹 탭 순서 — 종합은 나머지를 환산해 평균 내므로 맨 뒤다
METRICS = ["revenue", "kindness", "project", "care", "lesson", "overall"]

# 점수 원장을 그대로 headline 로 쓰는 항목들
_SCORE_FIELD = {
    ScoreCategory.KINDNESS: "kindness",
    ScoreCategory.PROJECT: "projectScore",
    ScoreCategory.ENV: "careScore",
    ScoreCategory.CLASS: "lessonScore",
}


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
        "projectScore": 0,
        "projectDone": 0,
        "projectTotal": 0,
        "careScore": 0,
        "care": 0,
        "lessons": 0,
        "lessonScore": 0,
        "lastRank": [0] * len(METRICS),
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

    # 친절·프로젝트·환경정비·수업 점수 — 전부 같은 원장이라 한 번에 접는다
    rows = (
        await db.execute(
            select(
                ScoreEvent.employee_id,
                ScoreEvent.category,
                func.coalesce(func.sum(ScoreEvent.points), 0),
            )
            .where(
                ScoreEvent.period == period,
                ScoreEvent.category.in_(list(_SCORE_FIELD)),
            )
            .group_by(ScoreEvent.employee_id, ScoreEvent.category)
        )
    ).all()
    for employee_id, category, points in rows:
        row = board.get(employee_id)
        if row is None:
            continue
        row[_SCORE_FIELD[category]] = int(points or 0)

    # 친절 근거 — 받은 설문 수 (점수는 위 원장에서 왔다)
    rows = (
        await db.execute(
            select(KindnessSurvey.praised_employee_id, func.count())
            .where(
                KindnessSurvey.submitted_at >= start,
                KindnessSurvey.submitted_at < end,
            )
            .group_by(KindnessSurvey.praised_employee_id)
        )
    ).all()
    for employee_id, count in rows:
        if employee_id in board:
            board[employee_id]["reviews"] = count

    # 환경정비 근거 — 그 달 수행 횟수
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

    # 수업 개수 — 그 달에 **수행한** 세션 싸인 수.
    # 담당(Member.owner_trainer_id) 이 아니라 수행자 기준이다 — 대타면 대타가 가져간다.
    rows = (
        await db.execute(
            select(SessionSign.performed_by_trainer_id, func.count())
            .where(SessionSign.signed_at >= start, SessionSign.signed_at < end)
            .group_by(SessionSign.performed_by_trainer_id)
        )
    ).all()
    for employee_id, count in rows:
        if employee_id in board:
            board[employee_id]["lessons"] = count

    # 프로젝트 근거 — 그 달 안에 기한이 있는 것 중 내가 담당인 것.
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
        return float(row["projectScore"])
    if metric == "care":
        return float(row["careScore"])
    if metric == "lesson":
        return float(row["lessons"])
    # 종합 — 항목마다 1등을 100점으로 두고 상대 위치를 평균 낸다.
    # 매출은 원, 수업은 개수라 단위가 달라서 그냥 더할 수 없다.
    total = 0.0
    parts = METRICS[:-1]
    for part in parts:
        top = max((_value(other, part, pool) for other in pool), default=0.0)
        if top > 0:
            total += _value(row, part, pool) / top * 100
    return total / len(parts)


def metric_value(row: dict, metric: str, pool: list[dict]) -> float:
    """항목별 값 — 밖에서 쓰는 이름 ([_value] 와 같다).

    추월 스캔이 '무슨 차이로 넘었나'를 재는 데 쓴다.
    """
    return _value(row, metric, pool)


def rank_board(board: list[dict]) -> dict[str, list[int]]:
    """사람별 항목 순위 — `{employeeId: [매출, 친절, 프로젝트, 환경, 수업, 종합]}`.

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
