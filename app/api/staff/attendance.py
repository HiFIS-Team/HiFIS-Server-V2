"""근태·휴가 라우터 — CLAUDE.md §6.9.

/attendance/scan: 바코드 → 출/퇴근 토글(근무시간 자동). /leaves: 신청·승인/거절.
목록은 지점 스코프(MEMBER=본인 지점).
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    ScanActor,
    branch_filter,
    branch_scope,
    get_current_user,
    require_role,
    scan_actor,
)
from app.core.periods import KST, period_range
from app.db.session import get_db
from app.enums import (
    AttendanceSource,
    AttendanceStatus,
    EmployeeStatus,
    LeaveStatus,
    LeaveType,
    Role,
    ScoreCategory,
)
from app.models.scoring.my_task import MyTask, MyTaskCheck
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.staff.attendance import (
    AttendanceDayOut,
    AttendanceOut,
    AttendanceRosterDayOut,
    AttendanceRosterGroupOut,
    AttendanceScanRequest,
    LeaveBalanceOut,
    LeaveReject,
    LeaveRequestCreate,
    LeaveRequestOut,
)
from app.services import notification_texts as ntext
from app.services.duty import duty_hours
from app.services.notifications import master_ids, notify, notify_bosses
from app.services.scoring import accrue_score

router = APIRouter(tags=["attendance"])

# 근무 외 출근 자동 점수 (§6.9) — 기본 근무시간보다 이 분수 이상 이르거나 늦으면 인정, 각 +점수(하루 최대 2회).
OFFHOURS_THRESHOLD_MIN = 60
OFFHOURS_POINTS = 10

# 야근 판정 — 설정 퇴근시간에서 이 분수를 넘기면 야근. 퇴근 스캔을 기다리지 않고
# **시계로도** 잡는다(아직 일하는 중이면 '출근'이 아니라 '야근'이다).
# 근무 외 출근 점수와 같은 값으로 둔다: 점수를 받는 날과 화면에 야근으로 뜨는 날이 갈리면 헷갈린다.
OVERTIME_THRESHOLD_MIN = OFFHOURS_THRESHOLD_MIN

# 지각 차감 (2026-08-18 대표 결정) — 지각할 때마다 **종합 점수**에서 뺀다.
# 1회 -10 · 2회 -15 · **3회부터 -20 고정.**
#
# **누적이다 — 달이 바뀌어도 안 되돌린다.** 매달 리셋하면 달마다 첫 지각이
# 제일 싸져서, 늘 지각하는 사람과 처음 지각한 사람이 같은 값을 문다.
LATE_PENALTY = (-10, -15, -20)

# 조기퇴근 유예 — 퇴근시간보다 이 분수까지 일찍 찍은 건 그냥 퇴근으로 본다.
# 정리하고 나오느라 몇 분 이른 사람까지 조기퇴근으로 부르면 매일 걸린다.
EARLY_LEAVE_GRACE_MIN = 20

# 자정을 넘겨 퇴근한 뒤 '퇴근'으로 남겨 두는 시간. 지나면 미출근으로 돌아간다.
# (자정 전에 퇴근했으면 날짜가 바뀌는 순간 저절로 미출근이 된다)
OVERNIGHT_GRACE_MIN = 60

# 이 시각(KST) 전의 첫 스캔은 **어제 퇴근**으로 본다 — 야근이 자정을 넘긴 경우다.
# 이보다 늦으면 평범한 출근 스캔이라 어제 기록을 건드리지 않는다.
OVERNIGHT_CHECKOUT_BEFORE_MIN = 5 * 60

# 직전 스캔에서 이 시간 안에 또 찍히면 **무시**한다 (2026-08-13 결정, 5분).
#
# 스캔은 토글이라 두 번째가 곧 퇴근이다. 스캐너가 한 번에 두 번 읽거나 직원이
# "안 찍혔나?" 하고 다시 대면 **출근 1분 뒤 퇴근**이 되어 조기퇴근으로 잡힌다
# (실제로 났다 — 07:25 출근 → 07:26 퇴근 → 근무 1분).
#
# 카운터 프로그램(`tools/scan/scan.ps1`)에도 같은 거르기가 있지만 그건 **그 PC
# 안에서만** 돈다. 폰으로 찍거나 PC 를 다시 켜면 통과하므로 서버에도 둔다.
RESCAN_IGNORE_MIN = 5


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _kst_min(dt: datetime) -> int:
    k = dt.astimezone(KST)
    return k.hour * 60 + k.minute


def _joined(employee: Employee) -> date:
    """그 사람이 가입한 날 (KST) — 첫날 판정 예외와 결근 판정의 기준이다."""
    return employee.joined_at.astimezone(KST).date()


def _attendance_status(
    rec: Attendance,
    shift_start: str | None,
    shift_end: str | None,
    now_kst: datetime,
    joined: date | None = None,
    branch_name: str | None = None,
) -> AttendanceStatus:
    """근무시간 대비 판정(§6.9) — 정상/지각/조기퇴근/야근. 근무시간 미설정이면 UNKNOWN.

    결근(근무일인데 기록 없음)은 근무 요일 스케줄이 없어 여기서 판정하지 않는다.

    **야근은 아직 안 간 사람에게만 붙는다** (2026-08-13 결정). 퇴근을 찍었으면
    아무리 늦어도 `NORMAL`(퇴근)이다 — 그러지 않으면 대표 화면의 야근 칸에
    '지금 센터에 있는 사람'과 '늦게까지 일하고 간 사람'이 섞인다. 출근·퇴근
    칸은 "지금 어디 있나"인데 야근만 두 뜻을 갖고 있었다.

    그래서 **지난 날짜에는 야근이 안 뜬다** — 퇴근을 찍었으면 퇴근이고,
    안 찍었으면 `NO_CHECKOUT`(퇴근누락)이다. 야근했다는 사실은 스캔할 때
    붙는 **초과근무 자동 점수**(`offhours:`)로 원장에 남는다.

    **가입한 날은 지각·조기퇴근을 안 매긴다** ([joined], 2026-08-13 결정).
    계정을 만들면서 그 자리에서 바코드를 대는데, 그게 근무 시작 시각보다 늦으면
    전원이 첫날부터 지각으로 찍힌다 (실제로 그랬다 — 8/12 가입자 전원). 야근은
    그대로 둔다 — 늦게까지 일한 것은 첫날이어도 사실이다.
    """
    if rec.check_in is None:
        return AttendanceStatus.UNKNOWN
    # 토·일·공휴일은 **당직이라 스캔된 대로만 보여준다** (2026-08-18 대표 결정).
    # 여러 명이 시간을 나눠 서는데 누가 어느 칸인지가 시스템에 없어서,
    # 몇 시에 왔는지로 지각·조기퇴근을 매길 근거가 없다.
    # (결근은 그대로 찍는다 — 그건 왔나 안 왔나지 몇 시냐가 아니다)
    if duty_hours(rec.date, branch_name) is not None:
        if rec.check_out is None:
            return (
                AttendanceStatus.NO_CHECKOUT
                if rec.date < now_kst.date()
                else AttendanceStatus.IN_PROGRESS
            )
        return AttendanceStatus.NORMAL
    if not shift_start or not shift_end:
        return AttendanceStatus.UNKNOWN
    first_day = joined is not None and rec.date == joined
    end_min = _hhmm_to_min(shift_end)
    late = _kst_min(rec.check_in) > _hhmm_to_min(shift_start) and not first_day
    if rec.check_out is None:
        if rec.date < now_kst.date():
            return AttendanceStatus.NO_CHECKOUT
        if _kst_min(now_kst) >= end_min + OVERTIME_THRESHOLD_MIN:
            return AttendanceStatus.OVERTIME  # 아직 안 갔고 퇴근시간을 넘겼다
        return AttendanceStatus.IN_PROGRESS
    # 자정을 넘겨 찍었으면 하루를 더해야 '퇴근시간보다 몇 분 이른가/늦은가'가 나온다.
    # 안 더하면 새벽 1시 퇴근이 0시 기준 90분이 되어 **조기퇴근**으로 잡힌다.
    out_min = _kst_min(rec.check_out) + (
        1440 if rec.check_out.astimezone(KST).date() > rec.date else 0
    )
    early = out_min < end_min - EARLY_LEAVE_GRACE_MIN and not first_day
    if late and early:
        return AttendanceStatus.LATE_AND_EARLY
    if late:
        return AttendanceStatus.LATE
    if early:
        return AttendanceStatus.EARLY_LEAVE
    # 늦게 찍었어도 **퇴근은 퇴근이다.** 여기서 야근을 돌려주면 대표 화면의
    # 야근 칸에 '아직 센터에 있는 사람'과 '늦게 갔다 온 사람'이 섞여서,
    # 밤에 화면을 봐도 누가 남아 있는지 알 수 없다 (2026-08-13 결정).
    # 야근한 사실은 스캔할 때 붙는 초과근무 점수로 남는다.
    return AttendanceStatus.NORMAL


def _still_overnight(prev: Attendance | None, now_kst: datetime) -> bool:
    """자정을 넘겨서도 아직 안 갔는가 — 그러면 오늘도 계속 **야근**이다.

    날짜만 보고 미출근으로 밀면 밤새 일하는 사람이 자정에 사라진다.
    [OVERNIGHT_CHECKOUT_BEFORE_MIN] 까지만 이어 준다 — 그 뒤의 스캔은 새 출근이라
    (스캔 규칙과 같은 경계다) 계속 야근으로 두면 퇴근을 잊은 사람이 종일 남는다.
    """
    if prev is None or prev.check_in is None or prev.check_out is not None:
        return False
    return _kst_min(now_kst) < OVERNIGHT_CHECKOUT_BEFORE_MIN


def _just_left_overnight(prev: Attendance | None, now_kst: datetime) -> bool:
    """자정을 넘겨 퇴근한 직후인가 — 그 뒤 [OVERNIGHT_GRACE_MIN] 분은 '퇴근'으로 남긴다.

    퇴근 스캔이 어제 기록에 붙어서, 그대로 두면 찍자마자 미출근으로 돌아간다.
    """
    if prev is None or prev.check_out is None:
        return False
    if prev.check_out.astimezone(KST).date() != now_kst.date():
        return False  # 어제 안에 퇴근했다 — 날짜가 바뀌었으니 이미 미출근이다
    return (now_kst - prev.check_out).total_seconds() <= OVERNIGHT_GRACE_MIN * 60


#: 대표·관리자에게 가는 스캔 알림에 덧붙이는 말 — **정상이 아닐 때만** 있다.
#: 여기 없는 상태(정상·근무중 등)는 시각만 적힌다.
_SCAN_NOTES = {
    AttendanceStatus.LATE: "지각",
    AttendanceStatus.EARLY_LEAVE: "조기 퇴근",
    AttendanceStatus.LATE_AND_EARLY: "지각 · 조기 퇴근",
    AttendanceStatus.OVERTIME: "야근",
}


def _absent_today(
    employee: Employee, now_kst: datetime, branch_name: str | None = None
) -> bool:
    """오늘 근무일인데 스캔이 없을 때 결근으로 볼지 — 퇴근 시간이 지났으면 결근이다.

    그 전에는 **미출근**(판정 없음)이다. 아침 9시에 결근으로 뜨면 아직 오는 중인
    사람을 결근으로 부르는 셈이라, 본인이 설정한 근무시간이 다 지나야 찍는다.
    근무시간을 설정 안 한 사람은 기준이 없어 판정하지 않는다.

    **가입한 날은 결근으로 안 찍는다** (2026-08-13 결정). 계정은 보통 근무 중에
    만들어져서 그날은 출근 스캔이 있을 리가 없다 — 실제로 오후 3시에 가입한
    두 사람이 그날 결근으로 찍혔다. 캘린더 쪽 `day <= joined_d` 와 같은 규칙이다.
    """
    if _joined(employee) == now_kst.date():
        return False
    # 토·일·공휴일은 **당직 종료 시각**이 기준이다 (2026-08-18). 본인이 설정한
    # 근무시간은 평일 것이라 그날에 들이대면 엉뚱한 시각에 결근이 찍힌다.
    # 부르는 쪽이 근무 요일인지를 이미 봤으므로 여기서는 시각만 본다.
    duty = duty_hours(now_kst.date(), branch_name)
    end = duty[1] if duty else employee.shift_end
    if not end:
        return False
    return _kst_min(now_kst) > _hhmm_to_min(end)


async def _award_offhours(
    db: AsyncSession, target: Employee, day_key: str, ref_suffix: str, kind_label: str
) -> None:
    """근무외출근 자동 점수 — (직원·근무일·방향)당 1회만 적립(퇴근 재스캔 멱등). 시스템 발생이라 created_by=None."""
    ref = f"offhours:{day_key}:{ref_suffix}"
    exists = await db.scalar(
        select(ScoreEvent).where(
            ScoreEvent.employee_id == target.id,
            ScoreEvent.source_ref_id == ref,
        )
    )
    if exists is not None:
        return
    await accrue_score(
        db,
        employee_id=target.id,
        branch_id=target.branch_id,
        category=ScoreCategory.CONTRIB,
        points=OFFHOURS_POINTS,
        reason=f"{kind_label} (자동)",
        source_ref_id=ref,
    )
    await notify(db, employee_id=target.id, **ntext.offhours_award(kind_label, OFFHOURS_POINTS))


async def _deduct_late(db: AsyncSession, target: Employee, day: date) -> None:
    """지각 차감 — **여태까지 지각한 횟수**가 커질수록 많이 뺀다 ([LATE_PENALTY]).

    점수 원장에 음수로 한 줄 넣는 것이 전부다. 랭킹 '종합'이 원장 전체 합이라
    (`services/ranking.py`) **넣기만 하면 종합 점수가 깎이고**, 매출·친절 같은
    다른 탭은 카테고리로 걸러서 영향이 없다.

    **하루에 한 번뿐이다** (`late:<날짜>`). 출근 스캔은 하루 한 번이지만
    기록을 지웠다 다시 찍는 경우가 있어 원장 쪽에서도 막는다 — 근무외출근
    점수와 같은 방식이다.

    대표·관리자는 `accrue_score` 가 알아서 건너뛴다 (점수를 매기는 쪽이라
    원장에 아예 안 들어간다). 그래서 여기서 권한을 따로 안 본다.
    """
    ref = f"late:{day.isoformat()}"
    exists = await db.scalar(
        select(ScoreEvent.id).where(
            ScoreEvent.employee_id == target.id, ScoreEvent.source_ref_id == ref
        )
    )
    if exists is not None:
        return
    before = (
        await db.scalar(
            select(func.count())
            .select_from(ScoreEvent)
            .where(
                ScoreEvent.employee_id == target.id,
                ScoreEvent.category == ScoreCategory.LATE,
            )
        )
    ) or 0
    nth = before + 1
    points = LATE_PENALTY[min(nth, len(LATE_PENALTY)) - 1]
    event = await accrue_score(
        db,
        employee_id=target.id,
        branch_id=target.branch_id,
        category=ScoreCategory.LATE,
        points=points,
        reason=f"지각 {nth}회 (자동)",
        source_ref_id=ref,
    )
    # 안 쌓였으면(대표·관리자) 알림도 안 보낸다 — 안 깎였는데 깎였다고 알리면 안 된다
    if event is not None:
        await notify(db, employee_id=target.id, **ntext.late_penalty(nth, points))


# ---------- 근태 ----------
async def _notify_task_missing(db: AsyncSession, target: Employee, day: date) -> None:
    """내 업무를 남기고 퇴근했으면 **본인과 대표에게** 알린다 (2026-08-14).

    공통 업무(환경정비)는 몇 번을 하든 자유라 누락이라는 게 없다. 내 업무는
    그날 다 해야 하는 목록이라, 안 한 채로 나가면 알려 줘야 한다.

    **업무를 하나도 안 정한 사람은 조용하다** — 할 일을 안 만든 것이지
    안 한 것이 아니다. 대표·관리자는 애초에 이 화면이 없어서 늘 0개다.
    """
    tasks = list(
        await db.scalars(
            select(MyTask)
            .where(MyTask.employee_id == target.id, MyTask.deleted_at.is_(None))
            .order_by(MyTask.sort, MyTask.created_at)
        )
    )
    if not tasks:
        return
    done = set(
        await db.scalars(
            select(MyTaskCheck.my_task_id).where(
                MyTaskCheck.my_task_id.in_([t.id for t in tasks]),
                MyTaskCheck.date == day,
            )
        )
    )
    left = [t.content for t in tasks if t.id not in done]
    if not left:
        return
    await notify(db, employee_id=target.id, **ntext.my_task_missing(left))
    # 대표에게만 — 관리자까지 받으면 매일 저녁 알림이 두 배가 된다
    for eid in await master_ids(db):
        if eid != target.id:
            await notify(db, employee_id=eid, **ntext.staff_task_missing(target.name, len(left)))


@router.post("/attendance/scan", response_model=AttendanceOut)
async def scan_attendance(
    payload: AttendanceScanRequest | None = Body(default=None),
    actor: ScanActor = Depends(scan_actor),
    db: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    """사람이 부를 수도 있고 **지점 단말**이 부를 수도 있다.

    단말은 `X-Terminal-Token` 헤더로 온다 (카운터 PC 에서 화면 없이 도는
    프로그램). 어느 쪽이든 **자기 지점 직원만** 찍을 수 있고, 전 지점은
    MASTER·ADMIN 뿐이다.
    """
    # 사번(emp_no) 스캔이면 그 주인(지점 스캐너 모드), 없으면 로그인 본인(하위호환)
    if payload is not None and payload.code:
        normalized = payload.code.strip().replace("-", "")  # 하이픈 유무 모두 허용
        target = await db.scalar(
            select(Employee).where(
                func.replace(Employee.emp_no, "-", "") == normalized,
                Employee.deleted_at.is_(None),
            )
        )
        if target is None:
            raise HTTPException(404, detail={"code": "EMP_NO_NOT_FOUND", "message": "등록되지 않은 사번입니다"})
        if not actor.all_branches and target.branch_id != actor.branch_id:
            raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 직원은 스캔할 수 없습니다"})
    elif actor.employee is not None:
        target = actor.employee
    else:
        # 단말에는 '본인'이 없다 — 사번을 안 주면 누구를 찍을지 알 수 없다
        raise HTTPException(400, detail={"code": "CODE_REQUIRED", "message": "사번이 필요합니다"})

    now = datetime.now(timezone.utc)
    now_kst = now.astimezone(KST)
    today = now_kst.date()  # KST 근무일 기준(자정 넘는 UTC 분리 방지 → 이른 출근도 같은 날 퇴근과 페어링)
    now_min = now_kst.hour * 60 + now_kst.minute
    # 토요일 당직 시간이 지점마다 달라서 이름이 필요하다 (화순 09~18 / 나머지 11~19)
    branch = await db.get(Branch, target.branch_id)
    branch_name = branch.name if branch else None
    # 오늘의 기준 시각 — 당직일이면 당직 시간, 아니면 본인이 설정한 근무시간
    in_duty = duty_hours(today, branch_name)
    start_ref = in_duty[0] if in_duty else target.shift_start
    record = (
        await db.execute(
            select(Attendance).where(
                Attendance.employee_id == target.id, Attendance.date == today
            )
        )
    ).scalar_one_or_none()

    # 야근이 자정을 넘긴 경우 — 새벽 첫 스캔은 **어제 퇴근**이다.
    # 그냥 두면 새벽 1시 퇴근이 오늘 출근으로 잡혀 어제는 퇴근 누락으로 남는다.
    overnight = False
    if record is None and now_min < OVERNIGHT_CHECKOUT_BEFORE_MIN:
        prev = (
            await db.execute(
                select(Attendance).where(
                    Attendance.employee_id == target.id,
                    Attendance.date == today - timedelta(days=1),
                )
            )
        ).scalar_one_or_none()
        if prev is not None and prev.check_in is not None and prev.check_out is None:
            record, overnight = prev, True

    # 방금 찍은 걸 또 찍었다 — 아무것도 안 하고 지금 상태를 그대로 돌려준다.
    # **알림도 안 보낸다** (본인에게도, 대표에게도). 한 번 찍은 일이다.
    if record is not None:
        last = record.check_out or record.check_in
        if last is not None and (now - last) < timedelta(minutes=RESCAN_IGNORE_MIN):
            out = AttendanceOut.model_validate(record)
            out.status = _attendance_status(
                record, target.shift_start, target.shift_end, now_kst, _joined(target), branch_name
            )
            return out

    if record is None:  # 첫 스캔 = 출근
        record = Attendance(
            employee_id=target.id, date=today, check_in=now, source=AttendanceSource.BARCODE
        )
        db.add(record)
        action = "출근"
        # 기준 출근시각보다 1시간+ 이르게 왔으면 조기출근 자동 점수.
        # **토·일·공휴일은 본인 근무시간이 아니라 당직 여는 시각을 본다** (2026-08-18).
        if start_ref and now_min <= _hhmm_to_min(start_ref) - OFFHOURS_THRESHOLD_MIN:
            await _award_offhours(db, target, today.isoformat(), "in", "조기 출근")
        # 지각이면 종합 점수에서 뺀다. **조건을 `_attendance_status` 의 지각과
        # 똑같이 맞춘다** — 화면에는 '지각'인데 점수는 안 깎이거나 그 반대면
        # 어느 쪽이 맞는지 알 수 없게 된다.
        #   · 당직일(토·일·공휴일)은 지각을 안 매긴다 — 사람마다 서는 칸이 다르다
        #   · 근무시간을 설정 안 했으면 판정 자체가 안 된다
        #   · 입사 첫날은 뺀다 (오전에 서류 쓰고 오후에 첫 스캔을 찍는다)
        if (
            in_duty is None
            and target.shift_start
            and target.shift_end
            and _joined(target) != today
            and now_min > _hhmm_to_min(target.shift_start)
        ):
            await _deduct_late(db, target, today)
    else:  # 두 번째 이후 = 퇴근(근무시간 갱신)
        # **오늘 첫 퇴근 스캔인가** — 내 업무 누락 알림을 여기서만 보낸다.
        # 퇴근을 여러 번 찍는 사람이 있어서, 안 가르면 누를 때마다 대표에게 간다.
        first_out = record.check_out is None
        record.check_out = now
        if record.check_in is not None:
            record.work_minutes = int((now - record.check_in).total_seconds() // 60)
        action = "퇴근"
        # 기본 퇴근보다 1시간+ 늦게 찍으면 초과근무 자동 점수(재스캔해도 하루 1회만).
        # 자정을 넘겼으면 하루를 더해야 '몇 분 늦었나'가 나온다. 점수는 그 근무일 몫이다.
        out_min = now_min + (1440 if overnight else 0)
        # 퇴근도 같다 — 당직일이면 당직 닫는 시각이 기준이다.
        # 기록이 어제 것일 수 있어 `record.date` 로 다시 고른다 (자정 넘긴 퇴근).
        out_duty = duty_hours(record.date, branch_name)
        end_ref = out_duty[1] if out_duty else target.shift_end
        if end_ref and out_min >= _hhmm_to_min(end_ref) + OFFHOURS_THRESHOLD_MIN:
            await _award_offhours(db, target, record.date.isoformat(), "out", "초과 근무")
        if first_out:
            await _notify_task_missing(db, target, record.date)
    # 스캔 즉시 알림(+웹푸시) — 스캔한 본인에게
    await notify(db, employee_id=target.id, **ntext.attendance_scan(action, now_kst))
    # 대표·관리자에게도 알린다 — 누가 왔고 누가 갔는지 (2026-08-11 대표 요청).
    # **정상이 아닐 때만** 한 마디 붙인다. '정상'을 매번 적으면 읽을 게 늘기만 한다.
    status = _attendance_status(
        record, target.shift_start, target.shift_end, now_kst, _joined(target), branch_name
    )
    await notify_bosses(
        db,
        exclude=target.id,
        **ntext.staff_attendance(target.name, action, now_kst, _SCAN_NOTES.get(status)),
    )
    await db.commit()
    await db.refresh(record)
    out = AttendanceOut.model_validate(record)
    out.status = status
    return out


@router.get("/attendance", response_model=list[AttendanceOut])
async def list_attendance(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    month: str | None = Query(None),
) -> list[AttendanceOut]:
    # 권한 가드(§60) — 캘린더·연차잔여와 동일. 남의 근태는 MASTER·ADMIN 만 본다.
    # 그 밖에는 남의 employeeId 를 넣든 안 넣든 **조용히 본인 것**으로 고정한다
    # (403 을 내지 않는 이유: 남을 달라고 조른 게 아니라 볼 수 있는 만큼 주는 것).
    # **MANAGER 도 여기 든다 (2026-08-14)** — 결재가 대표 전용이 되면서 점장이
    # 남의 근태를 볼 자리가 없어졌다.
    if current.role not in (Role.MASTER, Role.ADMIN):
        employee_id = current.id
    stmt = select(Attendance)
    if scope:
        stmt = stmt.join(Employee, Employee.id == Attendance.employee_id).where(
            Employee.branch_id == scope
        )
    if employee_id:
        stmt = stmt.where(Attendance.employee_id == employee_id)
    if month:
        start, end = period_range(month)
        stmt = stmt.where(Attendance.date >= start.date(), Attendance.date < end.date())
    rows = list((await db.execute(stmt.order_by(Attendance.date.desc()))).scalars().all())
    # 직원별 근무시간 로드 → 판정(정상/지각/조기퇴근)
    emp_ids = {r.employee_id for r in rows}
    shifts: dict[str, tuple[str | None, str | None]] = {}
    joined: dict[str, date] = {}
    if emp_ids:
        for eid, ss, se, at in (
            await db.execute(
                select(
                    Employee.id,
                    Employee.shift_start,
                    Employee.shift_end,
                    Employee.joined_at,
                ).where(Employee.id.in_(emp_ids))
            )
        ).all():
            shifts[eid] = (ss, se)
            joined[eid] = at.astimezone(KST).date()
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    out: list[AttendanceOut] = []
    for r in rows:
        ss, se = shifts.get(r.employee_id, (None, None))
        o = AttendanceOut.model_validate(r)
        o.status = _attendance_status(r, ss, se, now_kst, joined.get(r.employee_id))
        out.append(o)
    return out


@router.get("/attendance/calendar", response_model=list[AttendanceDayOut])
async def attendance_calendar(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    month: str = Query(...),
    employee_id: str | None = Query(None, alias="employeeId"),
) -> list[AttendanceDayOut]:
    """월 캘린더 — 하루하루 판정(정상/지각/조기퇴근/결근/휴가/휴무). 결근 = 근무일인데 과거·기록없음·휴가없음.

    근무 요일(work_days) 미설정이면 결근/휴무는 판정 못 하고 기록 있는 날만 반환한다.
    """
    target = current
    if employee_id and employee_id != current.id:
        # **남의 근태는 MASTER·ADMIN 만** (2026-08-14 에 MANAGER 를 뺐다).
        # 결재가 대표 전용이 되면서 점장은 남의 근태를 볼 자리가 없어졌다 —
        # 조직도 상세의 근태 요약 카드도 같이 안 그린다(`staff_detail.dart`).
        if current.role not in (Role.MASTER, Role.ADMIN):
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
        target = await db.get(Employee, employee_id)
        if target is None or target.deleted_at is not None:
            raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})

    start, end = period_range(month)
    start_d, end_d = start.date(), end.date()
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    today = now_kst.date()
    limit_d = min(end_d, today + timedelta(days=1))  # 미래는 판정 안 함(오늘까지)

    recs = {
        r.date: r
        for r in (
            await db.execute(
                select(Attendance).where(
                    Attendance.employee_id == target.id,
                    Attendance.date >= start_d,
                    Attendance.date < end_d,
                )
            )
        ).scalars().all()
    }
    leaves = list(
        (
            await db.execute(
                select(LeaveRequest).where(
                    LeaveRequest.employee_id == target.id,
                    LeaveRequest.status == LeaveStatus.APPROVED,
                    LeaveRequest.start_date < end_d,
                    LeaveRequest.end_date >= start_d,
                )
            )
        ).scalars().all()
    )

    def leave_on(day: date) -> LeaveRequest | None:
        for lv in leaves:
            if lv.start_date <= day <= lv.end_date:
                return lv
        return None

    work_days = set(target.work_days or [])
    joined_d = _joined(target)  # 입사 전은 판정 대상이 아니다
    out: list[AttendanceDayOut] = []
    day = start_d
    while day < limit_d:
        rec = recs.get(day)
        lv = leave_on(day)
        if rec is not None:  # 기록 있음 → 근무시간 대비 판정
            out.append(
                AttendanceDayOut(
                    date=day,
                    status=_attendance_status(
                        rec, target.shift_start, target.shift_end, now_kst, joined_d
                    ),
                    check_in=rec.check_in,
                    check_out=rec.check_out,
                    work_minutes=rec.work_minutes,
                )
            )
        elif lv is not None:  # 승인 휴가(반차 포함) → 결근 아님
            out.append(
                AttendanceDayOut(
                    date=day, status=AttendanceStatus.ON_LEAVE, leave_type=lv.type, half_period=lv.half_period
                )
            )
        elif day <= joined_d:
            # **가입한 날까지** 안 그린다 (2026-08-13 결정).
            #
            # 예전에는 `day < joined_d` 라 가입 **전날**까지만 뺐다. 그런데 계정은
            # 보통 근무 중에 만들어져서(실제로 오후 3시였다) 그날은 출근 스캔이
            # 있을 리가 없는데 근무 요일이면 그대로 결근으로 찍혔다.
            #
            # 가입 첫날 지각·조기퇴근을 안 매기는 것과 같은 이유다
            # (`_attendance_status` 의 `first_day`) — 그때 결근을 빠뜨렸다.
            pass
        elif work_days:
            # 토·일·공휴일이어도 **본인 근무 요일이면 결근을 찍는다** (2026-08-18).
            # 나와야 하는 날에 안 나온 것이라, 당직이라고 넘어가지 않는다.
            if day.isoweekday() not in work_days:
                out.append(AttendanceDayOut(date=day, status=AttendanceStatus.DAY_OFF))
            elif day < today:  # 근무일인데 과거·기록없음·휴가없음 → 결근
                out.append(AttendanceDayOut(date=day, status=AttendanceStatus.ABSENT))
            elif _absent_today(target, now_kst):  # 오늘 — 퇴근 시간까지 안 찍혔으면 결근
                out.append(AttendanceDayOut(date=day, status=AttendanceStatus.ABSENT))
            # 아직 근무 시간 안 → 미출근(판정 없음) → 생략
        # work_days 미설정이면 기록 없는 날은 판정 불가 → 생략
        day += timedelta(days=1)
    return out


@router.get(
    "/attendance/calendar/all",
    response_model=list[AttendanceRosterDayOut],
    dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))],
)
async def attendance_calendar_all(
    db: AsyncSession = Depends(get_db),
    # 앱 헤더의 지점 고르개가 쓴다 — MASTER·ADMIN 만 고를 수 있고
    # MANAGER 는 뭘 넣든 본인 지점으로 고정된다 (`branch_filter`).
    scope: str | None = Depends(branch_filter),
    month: str = Query(...),
) -> list[AttendanceRosterDayOut]:
    """전사 월 캘린더 — 하루마다 **누가 어떤 상태였는지**를 이름으로 묶어 준다.

    사람별 캘린더(`/attendance/calendar`)와 **같은 판정**을 전 직원에게 돌린 것이다.
    사람마다 부르면 인원수만큼 요청이 나가서 여기서 한 번에 준다.
    휴무·판정불가는 담지 않는다 — 대표 달력이 그릴 자리가 없다.

    **미출근(`NOT_IN`)은 여기서만 나온다** (2026-08-19). 두 자리를 덮는다.

    | | 언제 |
    |---|---|
    | 아직 안 왔다 | 오늘 · 근무일 · 스캔 없음 · 퇴근시간 전 |
    | 퇴근 스캔이 없다 | 새벽 5시를 넘기도록 안 찍음 (예전 `NO_CHECKOUT`) |

    사람별 캘린더·홈은 그대로 `NO_CHECKOUT`(퇴근 누락) 을 쓴다 — 본인 화면은
    "그날 왔는데 안 찍었다"가 보여야 근무일 수에서 안 빠진다.
    **MASTER·ADMIN 은 아예 빼고 센다** (출퇴근을 안 찍어서 매일 결근이 된다).
    MANAGER 는 branch_scope 가 자기 지점으로 좁혀 준다.
    """
    start, end = period_range(month)
    start_d, end_d = start.date(), end.date()
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    today = now_kst.date()
    limit_d = min(end_d, today + timedelta(days=1))  # 미래는 판정 안 함(사람별 캘린더와 같다)

    emp_stmt = select(Employee).where(
        Employee.deleted_at.is_(None),
        # 대표·관리자는 출퇴근을 안 찍는다 — 판정하면 근무시간이 지나는 순간
        # **매일 결근**으로 찍혀서 달력이 그 이름으로 채워진다 (실제로 그랬다).
        # 근태를 보는 쪽이지 대상이 아니라 아예 뺀다.
        Employee.role.notin_([Role.MASTER, Role.ADMIN]),
    )
    if scope:
        emp_stmt = emp_stmt.where(Employee.branch_id == scope)
    employees = list((await db.execute(emp_stmt)).scalars().all())
    if not employees:
        return []
    emp_ids = [e.id for e in employees]

    # 기록·휴가를 통째로 한 번씩 받아 사람별로 나눈다 (사람마다 질의하지 않는다)
    recs: dict[str, dict[date, Attendance]] = {eid: {} for eid in emp_ids}
    for r in (
        await db.execute(
            select(Attendance).where(
                Attendance.employee_id.in_(emp_ids),
                Attendance.date >= start_d,
                Attendance.date < end_d,
            )
        )
    ).scalars().all():
        recs[r.employee_id][r.date] = r

    leaves: dict[str, list[LeaveRequest]] = {eid: [] for eid in emp_ids}
    for lv in (
        await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.employee_id.in_(emp_ids),
                LeaveRequest.status == LeaveStatus.APPROVED,
                LeaveRequest.start_date < end_d,
                LeaveRequest.end_date >= start_d,
            )
        )
    ).scalars().all():
        leaves[lv.employee_id].append(lv)

    # 날짜 → 상태 → 이름들. 화면 순서는 앱이 정하므로 여기서는 만난 순으로 담는다.
    board: dict[date, dict[AttendanceStatus, list[str]]] = {}
    for emp in employees:
        mine = recs[emp.id]
        my_leaves = leaves[emp.id]
        work_days = set(emp.work_days or [])
        joined_d = _joined(emp)  # 입사 전은 판정 대상이 아니다
        day = start_d
        while day < limit_d:
            rec = mine.get(day)
            on_leave = next((lv for lv in my_leaves if lv.start_date <= day <= lv.end_date), None)
            status: AttendanceStatus | None = None
            if rec is not None:
                status = _attendance_status(
                    rec, emp.shift_start, emp.shift_end, now_kst, joined_d
                )
                if status == AttendanceStatus.UNKNOWN:
                    status = None  # 근무시간 미설정 — 그릴 자리가 없다
                elif status == AttendanceStatus.NO_CHECKOUT:
                    # **퇴근누락으로 안 부른다** (2026-08-19 대표 결정).
                    # 새벽 5시까지는 아직 안 간 것으로 보고 야근으로 두고,
                    # 그때까지도 스캔이 없으면 그냥 미출근이다.
                    status = (
                        AttendanceStatus.OVERTIME
                        if day == today - timedelta(days=1)
                        and _still_overnight(rec, now_kst)
                        else AttendanceStatus.NOT_IN
                    )
            elif on_leave is not None:
                status = AttendanceStatus.ON_LEAVE
            elif day <= joined_d:
                status = None  # 가입한 날까지 — 위 사람별 캘린더와 같은 규칙
            elif work_days and day.isoweekday() in work_days:
                if day < today or _absent_today(emp, now_kst):
                    status = AttendanceStatus.ABSENT
                else:
                    # 오늘인데 아직 근무시간이 안 지났다 — 미출근이다.
                    # **예전에는 안 담았다.** 그러면 아직 안 온 사람이 명단에서
                    # 통째로 빠져서, 달력이 남은 사람만 보고 `전원 출근` 으로
                    # 접었다 (2026-08-19 대표 지적 — 전원이 온 게 아닌데 그렇게 떴다).
                    status = AttendanceStatus.NOT_IN
            if status is not None:
                board.setdefault(day, {}).setdefault(status, []).append(emp.name)
            day += timedelta(days=1)

    return [
        AttendanceRosterDayOut(
            date=day,
            groups=[
                AttendanceRosterGroupOut(status=status, names=names)
                for status, names in board[day].items()
            ],
        )
        for day in sorted(board)
    ]


# ---------- 휴가 ----------
def _compute_days(leave_type: LeaveType, start, end) -> float:
    if leave_type == LeaveType.HALF:
        return 0.5
    return float((end - start).days + 1)


def annual_leave_granted(joined: date, as_of: date) -> float:
    """근로기준법 제60조 연차 부여(입사일 기준).

    - 계속근로 1년 미만: 1개월 개근 1일씩(최대 11) — 개근은 경과 개월수로 단순화.
    - 1년 이상: 15일 + (근속연수-1)//2 가산(3년차부터 2년마다 1일), 최대 25일.
    """
    months = (as_of.year - joined.year) * 12 + (as_of.month - joined.month)
    if as_of.day < joined.day:
        months -= 1
    months = max(months, 0)
    years = months // 12
    if years < 1:
        return float(min(months, 11))
    return float(min(15 + (years - 1) // 2, 25))


def _leave_year_start(joined: date, as_of: date) -> date:
    """이번 연차연도 시작 = as_of 이전의 가장 최근 입사기념일."""

    def anniv(year: int) -> date:
        try:
            return joined.replace(year=year)
        except ValueError:  # 2/29 입사
            return joined.replace(year=year, month=2, day=28)

    a = anniv(as_of.year)
    return a if a <= as_of else anniv(as_of.year - 1)


@router.get("/leaves", response_model=list[LeaveRequestOut])
async def list_leaves(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    status: LeaveStatus | None = Query(None),
    current: Employee = Depends(get_current_user),
) -> list[LeaveRequest]:
    # 결재하지 않는 사람은 **본인 것만** — 남의 휴가 사유까지 보이면 안 된다.
    # `/attendance` 와 같은 규칙이다 (403 대신 조용히 본인으로 고정).
    #
    # **MANAGER 도 여기 든다 (2026-08-14).** 승인·반려가 대표 전용이 되면서
    # 점장은 월차를 내는 쪽이지 받는 쪽이 아니다. 앱은 이미 본인 것만
    # 부르는데(`attendance_models.dart`) 서버가 열려 있어서, 토큰으로 직접
    # 부르면 지점 전원의 사유가 그대로 나왔다.
    if current.role in (Role.MEMBER, Role.MANAGER):
        employee_id = current.id
    stmt = select(LeaveRequest)
    if scope:
        stmt = stmt.join(Employee, Employee.id == LeaveRequest.employee_id).where(
            Employee.branch_id == scope
        )
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    result = await db.execute(stmt.order_by(LeaveRequest.start_date.desc()))
    return list(result.scalars().all())


@router.get("/leaves/balance", response_model=LeaveBalanceOut)
async def leave_balance(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    employee_id: str | None = Query(None, alias="employeeId"),
) -> LeaveBalanceOut:
    """연차 부여/사용/잔여 — 입사일 기준 근로기준법 산정. 기본 본인, employeeId 지정은 매니저↑."""
    target = current
    if employee_id and employee_id != current.id:
        # **남의 근태는 MASTER·ADMIN 만** (2026-08-14 에 MANAGER 를 뺐다).
        # 결재가 대표 전용이 되면서 점장은 남의 근태를 볼 자리가 없어졌다 —
        # 조직도 상세의 근태 요약 카드도 같이 안 그린다(`staff_detail.dart`).
        if current.role not in (Role.MASTER, Role.ADMIN):
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
        target = await db.get(Employee, employee_id)
        if target is None or target.deleted_at is not None:
            raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})

    as_of = datetime.now(timezone.utc).astimezone(KST).date()
    joined = target.joined_at.astimezone(KST).date()
    granted = annual_leave_granted(joined, as_of)
    year_start = _leave_year_start(joined, as_of)
    # 사용=승인+대기(신청중) 연차/반차 — 이번 연차연도. 병가·외근·기타는 연차 차감 아님.
    used_raw = await db.scalar(
        select(func.coalesce(func.sum(LeaveRequest.days), 0.0)).where(
            LeaveRequest.employee_id == target.id,
            LeaveRequest.type.in_([LeaveType.ANNUAL, LeaveType.HALF]),
            LeaveRequest.status.in_([LeaveStatus.APPROVED, LeaveStatus.PENDING]),
            LeaveRequest.start_date >= year_start,
        )
    )
    used = float(used_raw or 0.0)
    return LeaveBalanceOut(granted=granted, used=used, remaining=granted - used)


@router.post("/leaves", response_model=LeaveRequestOut, status_code=201)
async def create_leave(
    payload: LeaveRequestCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaveRequest:
    if payload.end_date < payload.start_date:
        raise HTTPException(400, detail={"code": "INVALID_RANGE", "message": "종료일이 시작일보다 빠릅니다"})
    # 반차면 오전/오후 필수, 그 외 타입은 시간대 무시(null)
    half_period = None
    if payload.type == LeaveType.HALF:
        if payload.half_period is None:
            raise HTTPException(400, detail={"code": "HALF_PERIOD_REQUIRED", "message": "반차는 오전/오후를 선택해야 합니다"})
        half_period = payload.half_period
    leave = LeaveRequest(
        employee_id=current.id,
        type=payload.type,
        half_period=half_period,
        start_date=payload.start_date,
        end_date=payload.end_date,
        days=_compute_days(payload.type, payload.start_date, payload.end_date),
        reason=payload.reason,
    )
    db.add(leave)
    # 결재자에게 알린다 — 신청이 올라온 걸 모르면 대기만 쌓인다.
    # **승인 권한이 있는 사람들**이다 (`/leaves/{id}/approve` = MASTER · MANAGER).
    # 점장은 자기 지점 것만 결재하므로 같은 지점만 부른다.
    approvers = (
        await db.scalars(
            select(Employee.id).where(
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
                Employee.id != current.id,
                or_(
                    Employee.role == Role.MASTER,
                    and_(
                        Employee.role == Role.MANAGER,
                        Employee.branch_id == current.branch_id,
                    ),
                ),
            )
        )
    ).all()
    text = ntext.leave_requested(
        current.name,
        ntext.leave_label(payload.type, half_period),
        payload.start_date,
        payload.end_date,
    )
    for eid in approvers:
        await notify(db, employee_id=eid, **text)
    await db.commit()
    await db.refresh(leave)
    return leave


async def _decide_leave(
    request_id: str, status: LeaveStatus, db: AsyncSession, reason: str | None = None
) -> LeaveRequest:
    leave = await db.get(LeaveRequest, request_id)
    if leave is None:
        raise HTTPException(404, detail={"code": "LEAVE_NOT_FOUND", "message": "휴가 신청을 찾을 수 없습니다"})
    if leave.status != LeaveStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_HANDLED", "message": "이미 처리된 신청입니다"})
    leave.status = status
    if status == LeaveStatus.REJECTED:
        leave.reject_reason = reason
    await notify(
        db,
        employee_id=leave.employee_id,
        **ntext.leave_decision(status == LeaveStatus.APPROVED, leave.start_date, leave.end_date, reason),
    )
    await db.commit()
    await db.refresh(leave)
    return leave


@router.post("/leaves/{request_id}/approve", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.MASTER))])
async def approve_leave(request_id: str, db: AsyncSession = Depends(get_db)) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.APPROVED, db)


@router.post("/leaves/{request_id}/reject", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.MASTER))])
async def reject_leave(
    request_id: str, payload: LeaveReject, db: AsyncSession = Depends(get_db)
) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.REJECTED, db, payload.reason)


@router.post("/leaves/{request_id}/cancel", response_model=LeaveRequestOut)
async def cancel_leave(
    request_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaveRequest:
    """신청자 본인이 대기중(PENDING) 휴가를 취소 → CANCELLED (이력 보존)."""
    leave = await db.get(LeaveRequest, request_id)
    if leave is None:
        raise HTTPException(404, detail={"code": "LEAVE_NOT_FOUND", "message": "휴가 신청을 찾을 수 없습니다"})
    if leave.employee_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 신청만 취소할 수 있습니다"})
    if leave.status != LeaveStatus.PENDING:
        raise HTTPException(400, detail={"code": "NOT_CANCELLABLE", "message": "대기중 신청만 취소할 수 있습니다"})
    leave.status = LeaveStatus.CANCELLED
    await db.commit()
    await db.refresh(leave)
    return leave
