"""랭킹 알림 잡 (CLAUDE.md §4.1) — 전사 통합 기준.

- announce_monthly_winners: 매월 1일, 전월 5개 분야 1등에게 축하 + 전원에게 통합 발표.
- ranking_change_scan: 5분마다, 이번 달 5개 분야 순위를 스냅샷과 비교 →
  밀려난 본인 + 어드민에게 순위 변동 알림. (write 경로 안 건드리는 폴링 diff)

**안정화 전에는 알림을 안 보낸다** — `RANKING_NOTIFY_FROM` 참고.
스캔·스냅샷은 그대로 돌아서, 다시 켜는 날 그동안 쌓인 변동이 터지지 않는다.
"""

from datetime import date, datetime, timezone

from sqlalchemy import delete, select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Role
from app.models.staff.employee import Employee
from app.models.scoring.rank_overtake import RankOvertake
from app.models.scoring.ranking_snapshot import RankingSnapshot
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.ranking import KIND_LABEL, RANKING_KINDS, compute_ranking
from app.services.ranking_board import METRICS, build_board, metric_value, rank_board


#: 랭킹 알림을 다시 켜는 날 (KST). 이 날부터 나간다.
#
# 쓰기 시작한 초반에는 점수가 몇 점만 들어와도 등수가 계속 뒤집혀서
# **5분마다 알림이 쏟아진다.** 자리가 잡힐 때까지 두 주 막아 둔다
# (2026-08-06 결정 — 안정화되면 그때 시작).
#
# **알림만 막고 스캔은 계속 돈다.** 스캔까지 멈추면 다시 켜는 날 첫 스캔이
# 2주치 변동을 한꺼번에 터뜨린다 — 막아 둔 뜻이 없어진다.
RANKING_NOTIFY_FROM = date(2026, 8, 20)


def ranking_notify_open(today: date) -> bool:
    """오늘 랭킹 알림을 보내도 되는가 — 더 미루려면 위 날짜만 옮기면 된다."""
    return today >= RANKING_NOTIFY_FROM


def _prev_period(today: date) -> str:
    y, m = today.year, today.month
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


async def _active_ids(db, *, roles: tuple[Role, ...] | None = None) -> list[str]:
    stmt = select(Employee.id).where(
        Employee.status == EmployeeStatus.ACTIVE, Employee.deleted_at.is_(None)
    )
    if roles:
        stmt = stmt.where(Employee.role.in_(roles))
    return list(await db.scalars(stmt))


async def announce_monthly_winners(now: datetime | None = None) -> None:
    """매월 1일 — 전월 5개 분야 1등 발표(전사 통합)."""
    now_utc = now or datetime.now(timezone.utc)
    today = now_utc.astimezone(KST).date()
    if not ranking_notify_open(today):
        return  # 안정화 전 — 랭킹 알림을 아예 안 보낸다
    period = _prev_period(today)
    async with SessionLocal() as db:
        winners: list[tuple[str, str]] = []       # (라벨, 이름)
        congrats: list[tuple[str, str]] = []       # (employee_id, 라벨)
        for kind in RANKING_KINDS:
            ranking = await compute_ranking(db, kind=kind, period=period)  # 전사 통합
            if not ranking:
                continue
            top = ranking[0]
            winners.append((KIND_LABEL[kind], top["name"]))
            congrats.append((top["employee_id"], KIND_LABEL[kind]))
        if not winners:
            return
        # 1등 개인 축하
        for eid, label in congrats:
            await notify(db, employee_id=eid, **ntext.ranking_winner(period, label))
        # 전원에게 통합 발표
        summary = " · ".join(f"{label} {name}" for label, name in winners)
        for eid in await _active_ids(db):
            await notify(db, employee_id=eid, **ntext.ranking_announce(period, summary))
        await db.commit()


async def ranking_change_scan(now: datetime | None = None) -> None:
    """5분마다 — 이번 달 순위 변동(누가 나를 앞질렀나) 감지 → 본인 + 어드민 알림."""
    now_utc = now or datetime.now(timezone.utc)
    period = now_utc.astimezone(KST).strftime("%Y-%m")
    # 안정화 전에는 **알림만** 건너뛴다 — 스캔과 스냅샷 갱신은 그대로 돈다.
    # 스캔까지 멈추면 다시 켜는 날 그동안 쌓인 변동이 한꺼번에 터진다.
    notify_open = ranking_notify_open(now_utc.astimezone(KST).date())
    async with SessionLocal() as db:
        admin_ids = await _active_ids(db, roles=(Role.MASTER, Role.ADMIN))
        for kind in RANKING_KINDS:
            ranking = await compute_ranking(db, kind=kind, period=period)  # 전사 통합
            new_rank = {r["employee_id"]: r["rank"] for r in ranking}
            names = {r["employee_id"]: r["name"] for r in ranking}
            snaps = (
                await db.scalars(
                    select(RankingSnapshot).where(
                        RankingSnapshot.kind == kind.value, RankingSnapshot.period == period
                    )
                )
            ).all()
            old_rank = {s.employee_id: s.rank for s in snaps}
            label = KIND_LABEL[kind]

            # 최초 스캔(스냅샷 없음)이면 baseline 만 세팅 — 오탐 방지
            changes: list[tuple[str, list[str], int, int]] = []
            if old_rank:
                for b, nb in new_rank.items():
                    ob = old_rank.get(b)
                    if ob is None or nb <= ob:
                        continue  # 신규 등장 / 유지 / 상승은 대상 아님
                    # b 를 앞지른 사람 = 예전엔 b 아래였는데 지금 b 위인 사람
                    overtakers = [
                        names.get(a, "누군가")
                        for a, na in new_rank.items()
                        if a in old_rank and old_rank[a] > ob and na < nb
                    ]
                    if overtakers:
                        changes.append((b, overtakers, ob, nb))

                if notify_open:
                    # 밀려난 본인 알림
                    for b, overtakers, ob, nb in changes:
                        who = ", ".join(overtakers[:3]) + ("…" if len(overtakers) > 3 else "")
                        await notify(db, employee_id=b, **ntext.ranking_drop(label, who, ob, nb))
                    # 어드민 요약(변동 있을 때만)
                    if changes:
                        lines = [
                            f"{names.get(b, '?')} {ob}→{nb}위(↑{overtakers[0]})"
                            for b, overtakers, ob, nb in changes
                        ]
                        body = " / ".join(lines[:6])
                        for aid in admin_ids:
                            await notify(db, employee_id=aid, **ntext.ranking_change_admin(label, body))

            # 스냅샷 갱신(교체)
            await db.execute(
                delete(RankingSnapshot).where(
                    RankingSnapshot.kind == kind.value, RankingSnapshot.period == period
                )
            )
            for r in ranking:
                db.add(
                    RankingSnapshot(
                        kind=kind.value, period=period,
                        employee_id=r["employee_id"], rank=r["rank"], points=r["points"],
                    )
                )
        await db.commit()


# ---------------------------------------------------------------------------
# 랭킹판 추월 기록 — 대표·관리자 랭킹 화면이 읽는다
# ---------------------------------------------------------------------------
#
# 위의 `ranking_change_scan` 과 **보는 값이 다르다.** 저쪽은 점수 원장
# (`RankingKind`) 기준이고, 여기는 앱 랭킹 화면이 그리는 판
# (`ranking_board.METRICS` — 매출·친절·프로젝트·환경·수업·종합) 기준이다.
# 화면에 뜨는 등수와 어긋나면 "추월했다는데 순위는 그대로"가 되므로
# 화면이 보는 값에 맞춘다.
#
# 알림은 안 보낸다 — 저쪽이 이미 밀려난 본인과 관리자에게 알린다.
# 여기서 또 보내면 같은 사건으로 두 번 울린다.


async def board_overtake_scan(now: datetime | None = None) -> None:
    """5분마다 — 랭킹판에서 자리가 바뀐 것을 [RankOvertake] 에 남긴다."""
    now_utc = now or datetime.now(timezone.utc)
    period = now_utc.astimezone(KST).strftime("%Y-%m")

    async with SessionLocal() as db:
        # 전사 판 하나만 만든다 — 앱도 전사로 받아서 지점은 화면에서 거른다
        board = await build_board(db, period=period)
        if not board:
            return
        ranks = rank_board(board)
        rows = {row["employeeId"]: row for row in board}

        for at, metric in enumerate(METRICS):
            kind = f"BOARD_{metric.upper()}"
            new_rank = {
                eid: places[at] for eid, places in ranks.items() if places[at] > 0
            }

            snaps = (
                await db.scalars(
                    select(RankingSnapshot).where(
                        RankingSnapshot.kind == kind, RankingSnapshot.period == period
                    )
                )
            ).all()
            old_rank = {s.employee_id: s.rank for s in snaps}

            # 첫 스캔이면 기준선만 세운다 — 없던 것과 비교하면 전원이 추월로 잡힌다
            if old_rank:
                for mover, mover_now in new_rank.items():
                    mover_before = old_rank.get(mover)
                    if mover_before is None or mover_now >= mover_before:
                        continue  # 새로 들어왔거나 그대로거나 밀렸다

                    # 앞지른 사람들 = 예전엔 mover 위였는데 지금 아래인 사람
                    passed_all = [
                        (old_rank[other], other)
                        for other, other_now in new_rank.items()
                        if other in old_rank
                        and old_rank[other] < mover_before
                        and other_now > mover_now
                    ]
                    if not passed_all:
                        continue

                    # **한 줄만 남긴다.** 종합처럼 상대값인 항목은 한 사람이 오르면
                    # 여러 명이 같이 밀려서, 다 적으면 카드가 같은 사건으로 꽉 찬다.
                    # 그중 **자리를 뺏긴 사람**(mover 가 지금 앉은 등수의 주인)을 고른다.
                    passed_all.sort()
                    passed = next(
                        (other for before, other in passed_all if before == mover_now),
                        passed_all[0][1],
                    )

                    gap = metric_value(rows[mover], metric, board) - metric_value(
                        rows[passed], metric, board
                    )
                    # 동점이면 추월이 아니다 — 자리만 흔들린 것이라 적을 것이 없다
                    if gap <= 0:
                        continue

                    db.add(
                        RankOvertake(
                            period=period,
                            metric=metric,
                            mover_id=mover,
                            passed_id=passed,
                            gap=gap,
                            rank=mover_now,
                        )
                    )

            # 기준선 갱신 (교체)
            await db.execute(
                delete(RankingSnapshot).where(
                    RankingSnapshot.kind == kind, RankingSnapshot.period == period
                )
            )
            for eid, place in new_rank.items():
                db.add(
                    RankingSnapshot(
                        kind=kind,
                        period=period,
                        employee_id=eid,
                        rank=place,
                        points=round(metric_value(rows[eid], metric, board)),
                    )
                )
        await db.commit()
