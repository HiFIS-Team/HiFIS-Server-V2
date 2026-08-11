"""결근 알림 — 대표·관리자에게 (2026-08-11 대표 요청).

출퇴근은 **스캔이 곧 사건**이라 그 자리에서 알리면 되는데(`attendance.scan`),
결근은 사건이 아니라 **판정**이다. "퇴근 시간이 지나도록 안 왔다"는 시계가
지나가야 알 수 있어서, 이 잡이 시계를 대신 본다.

**사람마다 퇴근 시간이 달라서** 정해진 한 시각에 몰아 보낼 수가 없다.
매시간 돌면서 **그 사람 퇴근 시간이 막 지난 그 정각에만** 한 번 보낸다.

    퇴근 18:00 → 19:00 정각에 판정      퇴근 18:30 → 19:00 정각에 판정
    퇴근 20:00 → 21:00 정각에 판정

이렇게 하면 **따로 기록을 남기지 않고도 하루 한 번**이 보장된다. 어느 정각에
보낼지가 퇴근 시간에서 바로 나오기 때문이다. 대신 그 정각에 서버가 멈춰 있었으면
그날 그 사람 것은 지나간다 — 결근은 근태 화면에 그대로 남으니 알림만 놓친다.

**23시 이후에 끝나는 근무는 판정하지 않는다** — 다음 정각이 자정을 넘겨
날짜가 바뀌어 버린다. 지금 그런 근무는 없다.
"""

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.api.staff.attendance import _absent_today, _hhmm_to_min
from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, LeaveStatus, Role
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.notifications import notify_bosses


async def absence_alerts(now: datetime | None = None) -> None:
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    today: date = now_kst.date()

    async with SessionLocal() as db:
        employees = (
            await db.execute(
                select(Employee).where(
                    Employee.status == EmployeeStatus.ACTIVE,
                    Employee.deleted_at.is_(None),
                    # 대표·관리자는 출퇴근을 안 찍는다 — 판정 대상이 아니다
                    # (전사 캘린더가 같은 이유로 빼고 센다, backend-gap 70번)
                    Employee.role.notin_([Role.MASTER, Role.ADMIN]),
                )
            )
        ).scalars().all()

        targets = [e for e in employees if _due_now(e, now_kst)]
        if not targets:
            return

        ids = [e.id for e in targets]
        # 오늘 스캔한 사람 — 한 번에 받아 온다 (사람마다 질의하지 않는다)
        scanned = set(
            (
                await db.scalars(
                    select(Attendance.employee_id).where(
                        Attendance.employee_id.in_(ids), Attendance.date == today
                    )
                )
            ).all()
        )
        # 오늘 승인된 휴가가 걸쳐 있는 사람 — 결근이 아니다
        on_leave = set(
            (
                await db.scalars(
                    select(LeaveRequest.employee_id).where(
                        LeaveRequest.employee_id.in_(ids),
                        LeaveRequest.status == LeaveStatus.APPROVED,
                        LeaveRequest.start_date <= today,
                        LeaveRequest.end_date >= today,
                    )
                )
            ).all()
        )

        sent = False
        for employee in targets:
            if employee.id in scanned or employee.id in on_leave:
                continue
            await notify_bosses(db, **ntext.staff_absent(employee.name))
            sent = True
        if sent:
            await db.commit()


def _due_now(employee: Employee, now_kst: datetime) -> bool:
    """지금이 이 사람의 결근을 판정할 **그 정각**인가

    근무 요일이 아니거나 근무 시간을 설정 안 했으면 판정하지 않는다 —
    기준이 없는 것을 결근이라 부를 수는 없다.
    """
    work_days = set(employee.work_days or [])
    if not work_days or now_kst.isoweekday() not in work_days:
        return False
    if not employee.shift_end:
        return False
    fire_hour = _hhmm_to_min(employee.shift_end) // 60 + 1
    if fire_hour > 23:  # 다음 정각이 자정을 넘긴다 — 날짜가 바뀌어 못 센다
        return False
    return now_kst.hour == fire_hour and _absent_today(employee, now_kst)
