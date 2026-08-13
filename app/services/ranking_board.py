"""랭킹판 집계 — 앱 랭킹 화면이 사람마다 보여주는 값들 (CLAUDE.md §4.1).

`/scores/ranking` 은 kind 별 **점수 합**만 준다. 앱 랭킹 화면은 그것 말고도
"신규 3 · 재등록 5", "리뷰 27건 · ★4.5", "3 / 4건", "이번 달 22회" 같은
**근거 한 줄**을 같이 보여준다. 그 값들이 서로 다른 테이블에 있어서 여기서 모은다.

항목마다 화면에 찍히는 단위가 다르다 — 매출은 **금액**, 수업은 **개수**,
나머지는 **점수 원장 합**이다. 원장을 그대로 쓰는 항목(친절·프로젝트·환경정비)은
업무 화면이 쌓아 올린 점수와 랭킹이 어긋나지 않는다.

**종합은 쌓은 점수를 그대로 더한 값이다** (2026-08-13 대표 결정). 매출만
단위가 달라서 [sales_points] 로 바꿔 **말일에 한 번** 얹는다.

한 달치를 한 번에 모아 사람별로 접어 준다 — 사람마다 쿼리를 날리면
인원수만큼 요청이 늘어난다.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import KST, period_range
from app.enums import RegistrationType, Role, ScoreCategory, VisitPath
from app.models.members.member import Member
from app.models.members.registration import Registration
from app.models.members.session_sign import SessionSign
from app.models.projects.project import Project
from app.models.scoring.env import EnvTaskLog
from app.models.scoring.kindness import KindnessSurvey
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.employee import Employee

# 앱 랭킹 탭 순서 — 종합은 나머지를 더한 값이라 맨 뒤다
METRICS = ["revenue", "kindness", "project", "care", "lesson", "overall"]

# 점수 원장을 그대로 headline 로 쓰는 항목들
_SCORE_FIELD = {
    ScoreCategory.KINDNESS: "kindness",
    ScoreCategory.PROJECT: "projectScore",
    ScoreCategory.ENV: "careScore",
    ScoreCategory.CLASS: "lessonScore",
    ScoreCategory.BLOG: "blogScore",
    ScoreCategory.INSTAGRAM: "instaScore",
    ScoreCategory.OT_PT: "otptScore",
    # 센터 기여도 — **랭킹 탭은 없지만** 점수 내역에는 줄로 뜬다.
    # 종합에는 원래부터 들어가고 있었는데 따로 안 내보내서, 내역을 다 더해도
    # 종합이 안 맞았다 (근무 외 출근 자동 10점이 여기 들어간다).
    ScoreCategory.CONTRIB: "contribScore",
}


def sales_points(revenue: int) -> int:
    """매출(원) → 종합에 얹는 점수. **만원 단위로 보고 0.25 를 곱한다.**

    대표님 계산 그대로다 — `500만 × 0.25 = 1,250,000` 에서 뒤의 0 네 개를 떼면
    125 이고, 그것이 곧 `500만 ÷ 1만 × 0.25` 다.

    | 매출 | 점수 |
    |---|---|
    | 1,000만 | 250 |
    | 500만 | 125 |
    | 100만 | 25 |

    **소수점은 버린다.** 급여의 `payroll.sales_points` 와 식은 같지만 거기는
    반올림이라 값이 1 점 다를 수 있다 — 랭킹은 "이만큼 벌면 이만큼"이 눈으로
    떨어져야 해서 버림으로 둔다.
    """
    return int(revenue / 10_000 * 0.25)


def _month_closed(period: str) -> bool:
    """그 달이 끝났는가 — **마지막 날부터** True.

    매출 점수를 종합에 얹는 시점이다. 지난달을 볼 때는 늘 True 다.
    """
    today = datetime.now(timezone.utc).astimezone(KST).date()
    start, end = period_range(period)
    last_day = (end.astimezone(KST) - timedelta(days=1)).date()
    return today >= last_day


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
        # 방문 경로 — 셋을 따로 준다. 랭킹 내역이 갈라서 보여준다
        "blogScore": 0,
        "instaScore": 0,
        "otptScore": 0,
        # 센터 기여도 — 근무 외 출근 자동 점수와 아이디어·목표 업무 부여분
        "contribScore": 0,
        # 종합의 재료 — 그 달 점수 원장 합(카테고리별로 음수는 0), 그리고
        # 말일에 한 번 얹는 매출 점수. 둘을 더한 것이 종합이다.
        "ledger": 0,
        "salesScore": 0,
        "lastRank": [0] * len(METRICS),
    }


async def build_board(
    db: AsyncSession, *, period: str, branch_id: str | None = None
) -> list[dict]:
    """한 달치 랭킹판. 순위는 매기지 않고 **값만** 채운다."""
    start, end = period_range(period)

    people = (
        await db.scalars(
            select(Employee).where(
                Employee.deleted_at.is_(None),
                # 대표·관리자는 줄 세우는 쪽이지 서는 쪽이 아니다 (2026-08-11 대표 결정).
                # 근태 판정에서 뺀 것과 같은 이유다 (backend-gap 70번).
                Employee.role.notin_([Role.MASTER, Role.ADMIN]),
            )
        )
    ).all()
    if branch_id:
        people = [p for p in people if p.branch_id == branch_id]
    board = {p.id: _blank(p) for p in people}

    # 매출 — 그 달에 등록된 등록권의 결제액. 신규/재등록을 따로 센다
    #
    # **워크인은 뺀다** (2026-08-13 대표 결정). 센터를 보고 제 발로 온 사람이라
    # 직원이 끌어온 실적이 아니다. 방문 경로 점수를 줄 때 워크인을 빼는 것과
    # 같은 기준이다 (`VISIT_PATH_SCORE`).
    #
    # **급여는 그대로다** — 커미션은 워크인도 포함해서 계산한다. 랭킹에서만 뺀다.
    rows = (
        await db.execute(
            select(
                Registration.trainer_id,
                Registration.type,
                func.coalesce(func.sum(Registration.price_paid), 0),
                func.count(),
            )
            .join(Member, Member.id == Registration.member_id)
            .where(
                Registration.created_at >= start,
                Registration.created_at < end,
                Member.visit_path.is_distinct_from(VisitPath.WALK_IN),
            )
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

    # 점수 원장 — **전 카테고리**를 한 번에 접는다.
    #
    # 탭에 쓰는 것은 `_SCORE_FIELD` 에 있는 것들뿐이지만, 종합은 쌓은 점수를
    # 그대로 더하므로 센터 기여도(CONTRIB)·동료평가처럼 탭이 없는 것도 들어간다.
    #
    # **급여 마감이 넣는 매출성과(`sales:*`)는 뺀다** — 종합의 매출 점수를
    # 여기서 따로 계산하므로 그대로 두면 같은 매출이 두 번 세어진다.
    rows = (
        await db.execute(
            select(
                ScoreEvent.employee_id,
                ScoreEvent.category,
                func.coalesce(func.sum(ScoreEvent.points), 0),
            )
            .where(
                ScoreEvent.period == period,
                func.coalesce(ScoreEvent.source_ref_id, "").not_like("sales:%"),
            )
            .group_by(ScoreEvent.employee_id, ScoreEvent.category)
        )
    ).all()
    for employee_id, category, points in rows:
        row = board.get(employee_id)
        if row is None:
            continue
        # 카테고리마다 음수는 0 으로 자른 뒤 더한다 — 한 항목을 깎았다고
        # 다른 항목에서 쌓은 점수까지 잡아먹으면 안 된다
        row["ledger"] += max(0, int(points or 0))
        if category not in _SCORE_FIELD:
            continue
        # 음수는 0 으로 (2026-08-13 결정) — MASTER 가 프로젝트 점수를 깎으면 합이
        # 마이너스가 될 수 있는데 **랭킹판에는 `-` 를 안 찍는다.** 깎인 사실은
        # 업무 화면의 점수 내역에 그대로 남는다. 여기서 자르면 탭 값과 종합 환산이
        # 같은 값을 본다 — 한쪽만 자르면 둘이 어긋난다.
        row[_SCORE_FIELD[category]] = max(0, int(points or 0))

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
    # 매출 점수 — **말일부터** 종합에 얹는다 (2026-08-13 대표 결정).
    #
    # 매출은 원 단위라 그대로 못 더한다. 급여가 쓰는 것과 같은 식으로 바꾼다:
    # 만원 단위로 보고 0.25 를 곱한다 (500만원 → 125, 1000만원 → 250).
    #
    # **달이 끝나야 붙는다.** 월중에는 0 이라 종합에 매출이 안 보이고, 마지막
    # 날부터 한 번에 들어온다. 나머지 점수(환경정비·수업 등)는 그때그때 반영된다.
    if _month_closed(period):
        for row in board.values():
            row["salesScore"] = sales_points(row["revenue"])
    for row in board.values():
        row["overall"] = row["ledger"] + row["salesScore"]

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
    if metric == "visit":
        # 방문 경로 — 탭은 없지만 점수는 종합(원장 합)에 그대로 들어간다.
        # 여기 남겨 둔 것은 추월 스캔이 "무슨 차이로 넘었나"를 잴 때 쓰기 때문이다.
        return float(row["blogScore"] + row["instaScore"] + row["otptScore"])
    # 종합 — **쌓은 점수를 그대로 더한다** (2026-08-13 대표 결정).
    #
    # 예전에는 항목마다 1등을 100 으로 놓고 평균을 냈는데, 그러면 한 항목에서
    # 압도적 1등을 해도 종합은 20점이 천장이라 "133점인데 왜 20점이냐"가 됐다.
    # 지금은 환경정비 133점이 종합에 133 으로 들어간다 — 아무나 검산할 수 있다.
    #
    # 매출만 단위가 다르다(원). [sales_points] 로 점수로 바꿔서 **말일에 한 번**
    # 얹는다 — 그 전에는 0 이다.
    return float(row["ledger"] + row["salesScore"])


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
