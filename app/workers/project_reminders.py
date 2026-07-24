"""프로젝트 마감 리마인더 — 매시간 실행 (CLAUDE.md §9.5).

- 마감 전(미완료): 매일 09:00 KST 1회 'D-N' 푸시.
- 마감 당일: 매시간 푸시(방해금지 없음 — 대표 요청).
- 마감 초과(누락): 1회만 '누락' 알림(+웹푸시). overdue_notified_at 로 멱등.
- 완료(진행률 100%)는 대상에서 제외.
반복 리마인더는 push-only(알림함 폭주 방지), 누락만 앱 내 알림으로 남긴다.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus
from app.models.collab.project import Project
from app.models.org.employee import Employee
from app.services import notification_texts as ntext
from app.services.notifications import notify, send_push


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
            due_date = p.due.astimezone(KST).date()
            if today < due_date:
                # 마감 전 — 하루 1회(오전 9시 KST)
                if now_kst.hour == 9:
                    d = (due_date - today).days
                    for eid in assignees:
                        await send_push(db, employee_id=eid, **ntext.project_due_soon(d, p.title))
            elif today == due_date:
                # 마감 당일 — 매시간
                for eid in assignees:
                    await send_push(db, employee_id=eid, **ntext.project_due_today(p.title))
            elif p.overdue_notified_at is None:
                # 마감 초과 — 누락 1회(앱 내 알림 + 푸시)
                for eid in assignees:
                    await notify(db, employee_id=eid, **ntext.project_overdue(p.title))
                p.overdue_notified_at = now_utc
        await db.commit()
