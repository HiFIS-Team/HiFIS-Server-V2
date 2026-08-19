"""프로젝트 마감 리마인더 — 매시간 실행 (CLAUDE.md §9.5).

- 마감 전(미완료): 매일 09:00 KST 1회 'D-N' 푸시.
- 마감 당일: 매시간 푸시(방해금지 없음 — 대표 요청).
- 마감 초과(누락): 1회만 '누락' 알림(+웹푸시). overdue_notified_at 로 멱등.
- 완료(진행률 100%)는 대상에서 제외.
반복 리마인더는 push-only(알림함 폭주 방지), 누락만 앱 내 알림으로 남긴다.

**MASTER·ADMIN 은 참여 멤버여도 이 알림을 안 받는다** (2026-08-19 대표 결정).
직원이 만든 프로젝트에 대표를 참여 멤버로 넣으면 마감까지 매일 D-N 푸시가
대표 폰에 갔다. 대표·관리자가 받아야 하는 것은 **마감이 지난 뒤 누가 누락했는지**
(`notify_bosses`) 이고, 그건 아래에 그대로 있다.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Role
from app.models.projects.project import Project
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.notifications import notify, notify_bosses, send_push


async def _active_assignees(db, assignee_ids: list[str]) -> list[str]:
    if not assignee_ids:
        return []
    rows = await db.scalars(
        select(Employee.id).where(
            Employee.id.in_(assignee_ids),
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.deleted_at.is_(None),
        )
    )
    return list(rows)


async def _reminder_targets(db, assignee_ids: list[str]) -> list[str]:
    """리마인더를 **실제로 받을** 사람 — 참여 멤버에서 MASTER·ADMIN 을 뺀다.

    `_active_assignees` 와 갈라 둔 이유가 있다. 저쪽은 **프로젝트를 건너뛸지**
    판단하고 누락 알림에 이름을 싣는 데 쓴다. 여기서 같이 빼 버리면 참여 멤버가
    대표뿐인 프로젝트는 목록이 비어 `continue` 로 빠지고, **마감이 지나도
    누락 알림이 아무 데도 안 간다.**
    """
    if not assignee_ids:
        return []
    rows = await db.scalars(
        select(Employee.id).where(
            Employee.id.in_(assignee_ids),
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.deleted_at.is_(None),
            Employee.role.notin_([Role.MASTER, Role.ADMIN]),
        )
    )
    return list(rows)


async def _names(db, employee_ids: list[str]) -> str:
    """`김트레이너 · 박FC` — 대표에게 **누가** 누락했는지 보여주려고 붙인다"""
    rows = await db.scalars(select(Employee.name).where(Employee.id.in_(employee_ids)))
    return " · ".join(rows)


async def project_reminders(now: datetime | None = None) -> None:
    now_utc = now or datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)
    today = now_kst.date()
    async with SessionLocal() as db:
        projects = (
            await db.execute(select(Project).where(Project.progress < 100))
        ).scalars().all()
        for p in projects:
            assignees = await _active_assignees(db, p.assignee_ids)
            if not assignees:
                continue
            # 실제로 알림을 받는 사람 — 대표·관리자는 빠진다
            targets = await _reminder_targets(db, p.assignee_ids)
            due_date = p.due.astimezone(KST).date()
            if today < due_date:
                # 마감 전 — 하루 1회(오전 9시 KST)
                if now_kst.hour == 9:
                    d = (due_date - today).days
                    for eid in targets:
                        await send_push(db, employee_id=eid, **ntext.project_due_soon(d, p.title, p.id))
            elif today == due_date:
                # 마감 당일 — 매시간
                for eid in targets:
                    await send_push(db, employee_id=eid, **ntext.project_due_today(p.title, p.id))
            elif p.overdue_notified_at is None:
                # 마감 초과 — 누락 1회(앱 내 알림 + 푸시)
                for eid in targets:
                    await notify(db, employee_id=eid, **ntext.project_overdue(p.title, p.id))
                # 대표·관리자에게도 — **누가** 누락했는지까지 (2026-08-11 대표 요청)
                await notify_bosses(
                    db, **ntext.project_overdue_admin(p.title, await _names(db, assignees), p.id)
                )
                p.overdue_notified_at = now_utc
        await db.commit()
