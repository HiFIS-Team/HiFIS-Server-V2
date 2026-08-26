"""출퇴근 단말 침묵 감지 — 대표에게 (2026-08-26).

## 왜 만들었나

화순에서 "바코드가 안 된다"는 말이 왔는데 **서버 쪽에 아무 흔적이 없었다.**
성공도 실패도 없이 요청 자체가 안 왔다 — 카운터 PC 의 프로그램이 안 돌면
읽은 값이 PC 밖으로 못 나가기 때문이다.

제일 나쁜 건 **스캐너 부저가 그때도 삑 소리를 낸다**는 것이다. 찍은 사람은
됐다고 믿고 들어가고, 저녁이 되면 `absence_alerts` 가 돌아서 **그날 나온
사람 전원이 결근으로** 대표에게 간다. 실제로 화순 네 명이 그럴 뻔했다.

`attendance.scan` 의 실패 알림은 이걸 못 잡는다. 저건 **온 요청이 튕긴 것**을
알리는 자리인데, 여기서는 요청이 아예 안 온다.

## 어떻게 가르나

'조용하다'만으로는 고장인지 아무도 안 온 것인지 모른다. 그래서 단말이 5분마다
보내는 생존 신호를 같이 본다.

    started_at 이 없다        옛 스크립트 — 살았는지 죽었는지 **알 수 없다**
    하트비트가 멎었다          PC 가 꺼졌거나 프로그램이 죽었다
    하트비트는 오는데 포트 null  프로그램은 도는데 **스캐너를 못 찾는다**
    하트비트·포트 다 정상       기계는 멀쩡하다 → **안 알린다** (진짜 아무도 안 온 것)

마지막 줄이 중요하다. 멀쩡한데 아무도 안 찍은 것은 고장이 아니라 사람 일이고,
그건 저녁에 `absence_alerts` 가 이미 알린다. 여기서 또 알리면 같은 사실이
두 번 온다.

## 언제 판정하나

**그 지점에서 오늘 제일 먼저 일 시작하는 사람의 근무 시작 시각**이 지나고
[GRACE_MIN] 이 더 지나면 본다. 그 전에는 조용한 게 정상이다.

## 하루 한 번만

`alerted_at` 으로 묶는다. 알림 원장으로 세면 단말별로 못 가른다 — 같은 종류가
지점 수만큼 쌓여서 한 지점이 알림을 받으면 나머지가 조용해진다.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.staff.attendance import _hhmm_to_min
from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Role
from app.models.auth.scan_terminal import ScanTerminal
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.duty import duty_hours
from app.services.notifications import master_ids, notify

logger = logging.getLogger(__name__)

# 첫 근무 시작에서 이만큼 지나야 본다 — 정각에 재면 오는 중인 사람을 고장이라 부른다
GRACE_MIN = 45

# 하트비트가 이 시간 넘게 안 오면 죽은 것으로 본다.
# 신호는 5분마다라 넉넉히 잡는다 — 재시작·일시적 네트워크 끊김에 안 걸리게.
HEARTBEAT_STALE_MIN = 20


async def scan_terminal_watch(now: datetime | None = None) -> None:
    now_utc = now or datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)
    today: date = now_kst.date()
    now_min = now_kst.hour * 60 + now_kst.minute

    async with SessionLocal() as db:
        terminals = list(
            (
                await db.scalars(
                    select(ScanTerminal).where(ScanTerminal.revoked_at.is_(None))
                )
            ).all()
        )
        if not terminals:
            return

        sent = False
        for terminal in terminals:
            # 오늘 이미 알렸으면 넘어간다
            if terminal.alerted_at is not None:
                if terminal.alerted_at.astimezone(KST).date() == today:
                    continue

            start_min = await _first_shift_min(db, terminal.branch_id, today)
            if start_min is None:
                continue  # 오늘 그 지점에 근무 예정자가 없다 — 조용한 게 정상이다
            if now_min < start_min + GRACE_MIN:
                continue  # 아직 이르다

            # 오늘 사람이 찍은 적이 있으면 단말은 멀쩡하다
            if (
                terminal.last_used_at is not None
                and terminal.last_used_at.astimezone(KST).date() == today
            ):
                continue

            reason = _diagnose(terminal, now_utc)
            if reason is None:
                continue  # 기계는 멀쩡하다 — 결근은 저녁에 absence_alerts 가 알린다

            logger.warning("단말 침묵: %s — %s", terminal.name, reason)
            text = ntext.scan_terminal_silent(terminal.name, reason)
            for eid in await master_ids(db):
                await notify(db, employee_id=eid, **text)
            terminal.alerted_at = now_utc
            sent = True

        if sent:
            await db.commit()


def _diagnose(terminal: ScanTerminal, now_utc: datetime) -> str | None:
    """무엇이 죽었나 — 알릴 필요가 없으면 None.

    **정상인데 조용한 경우에 None 을 준다.** 그건 고장이 아니라 아무도 안 온
    것이고, 저녁에 결근 알림이 따로 나간다.
    """
    if terminal.started_at is None and terminal.heartbeat_at is None:
        # 옛 스크립트가 도는 단말 — 살았는지 죽었는지 알 방법이 없다.
        # **'꺼져 있다'고 단정하지 않는다.** 모르는 것을 아는 척하면 안 된다.
        return "출근 시간이 지났는데 스캔이 한 건도 없어요 (단말 상태를 알 수 없어요)"

    stale = now_utc - timedelta(minutes=HEARTBEAT_STALE_MIN)
    if terminal.heartbeat_at is None or terminal.heartbeat_at < stale:
        when = (
            f" (마지막 신호 {terminal.heartbeat_at.astimezone(KST):%m/%d %H:%M})"
            if terminal.heartbeat_at
            else ""
        )
        return f"카운터 PC 가 꺼져 있거나 프로그램이 안 돌고 있어요{when}"

    if terminal.scanner_port is None:
        return "프로그램은 도는데 스캐너를 못 찾고 있어요 (케이블·전원 확인)"

    # 프로그램도 스캐너도 정상이다 — 진짜 아무도 안 찍은 것이다
    return None


async def _first_shift_min(
    db: AsyncSession, branch_id: str, today: date
) -> int | None:
    """오늘 그 지점에서 **제일 먼저 시작하는** 근무 시각(분). 없으면 None.

    당직일이면 당직 시간이 이긴다 — 토요일 화순은 09시, 나머지는 11시라
    사람 설정과 다르다 (`duty_hours` 와 같은 기준을 쓴다).
    """
    branch = await db.get(Branch, branch_id)
    in_duty = duty_hours(today, branch.name if branch else None)
    weekday = today.isoweekday()

    employees = (
        await db.scalars(
            select(Employee).where(
                Employee.branch_id == branch_id,
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
                # 대표·관리자는 출퇴근을 안 찍는다 — 판정 대상이 아니다
                # (전사 캘린더·결근 알림과 같은 이유, backend-gap 70번)
                Employee.role.notin_([Role.MASTER, Role.ADMIN]),
            )
        )
    ).all()

    starts: list[int] = []
    for employee in employees:
        # **근무 요일을 먼저 본다.** 당직일이라고 전원이 나오는 게 아니다 —
        # 여기를 건너뛰면 아무도 안 나오는 날(일요일 공휴일 등)에도 판정이
        # 서서 헛알림이 간다 (만들 때 실제로 그랬다).
        work_days = set(employee.work_days or [])
        if not work_days or weekday not in work_days:
            continue
        # 나오는 사람이면, 그날 기준 시각은 당직일일 때 당직 시간이 이긴다
        # (`scan_attendance` 의 `start_ref` 와 같은 규칙)
        if in_duty:
            starts.append(_hhmm_to_min(in_duty[0]))
            continue
        if not employee.shift_start:
            continue
        starts.append(_hhmm_to_min(employee.shift_start))

    return min(starts) if starts else None
