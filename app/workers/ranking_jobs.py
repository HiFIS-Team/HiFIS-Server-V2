"""랭킹 알림 잡 (CLAUDE.md §4.1) — 전사 통합 기준.

- announce_monthly_winners: 매월 1일, 전월 5개 분야 1등에게 축하 + 전원에게 통합 발표.
- ranking_change_scan: 5분마다, 이번 달 5개 분야 순위를 스냅샷과 비교 →
  밀려난 본인 + 어드민에게 순위 변동 알림. (write 경로 안 건드리는 폴링 diff)
"""

from datetime import date, datetime, timezone

from sqlalchemy import delete, select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Role
from app.models.staff.employee import Employee
from app.models.scoring.ranking_snapshot import RankingSnapshot
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.ranking import KIND_LABEL, RANKING_KINDS, compute_ranking


def _prev_period(today: date) -> str:
    y, m = today.year, today.month
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


async def _active_ids(db, *, role: Role | None = None) -> list[str]:
    stmt = select(Employee.id).where(
        Employee.status == EmployeeStatus.ACTIVE, Employee.deleted_at.is_(None)
    )
    if role is not None:
        stmt = stmt.where(Employee.role == role)
    return list(await db.scalars(stmt))


async def announce_monthly_winners(now: datetime | None = None) -> None:
    """매월 1일 — 전월 5개 분야 1등 발표(전사 통합)."""
    now_utc = now or datetime.now(timezone.utc)
    period = _prev_period(now_utc.astimezone(KST).date())
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
    async with SessionLocal() as db:
        admin_ids = await _active_ids(db, role=Role.ADMIN)
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
