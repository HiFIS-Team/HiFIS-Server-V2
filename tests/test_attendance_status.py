"""근태 판정 — `backend-gap.md` 69번의 **손으로 재 본 표를 그대로 옮긴 것**이다.

그 문서에는 이런 줄이 적혀 있다.

    17:00 조기퇴근 · 17:39 조기퇴근 · 17:40 퇴근 · 17:59 퇴근 · 18:00 퇴근
    19:00 야근 · 자정 넘겨 01:30 야근 · 02:31 미출근

**사람이 한 번 재고 마크다운에 적어 둔 값들이다.** 실행되는 자리가 아니라서
다음에 코드를 고치면 아무도 다시 안 재 본다 — 그래서 여기로 옮긴다.

깨지면 **고치기 전에 의도한 변경인지 먼저 확인한다.** 이 판정 하나가
홈 카드 · 근태 달력 · 조직도 상태 점 · 대표 전사 달력에 같이 쓰인다.
"""

import pytest

from app.api.staff.attendance import (
    EARLY_LEAVE_GRACE_MIN,
    OVERTIME_THRESHOLD_MIN,
    _attendance_status,
)
from app.enums import AttendanceStatus
from app.models.staff.attendance import Attendance

from tests.helpers import at, day

# 평범한 평일 근무 — 문서의 표가 쓰는 기준
SHIFT = ("09:00", "18:00")
WORKDAY = "2026-08-13"  # 목요일 (당직일이 아니다 — 주말·공휴일은 규칙이 다르다)
NOW = at(WORKDAY, "23:00")  # 그날이 이미 다 지난 시점에서 본다


def rec(check_in: str | None = "09:00", check_out: str | None = None, *, out_day: str | None = None):
    return Attendance(
        employee_id="e1",
        date=day(WORKDAY),
        check_in=at(WORKDAY, check_in) if check_in else None,
        check_out=at(out_day or WORKDAY, check_out) if check_out else None,
    )


def judge(a: Attendance, now=NOW, joined=None) -> AttendanceStatus:
    return _attendance_status(a, SHIFT[0], SHIFT[1], now, joined)


# ── 퇴근 시각별 판정 — 문서의 표 그대로 ──────────────────────────────────

@pytest.mark.parametrize(
    "check_out, expected",
    [
        ("17:00", AttendanceStatus.EARLY_LEAVE),
        ("17:39", AttendanceStatus.EARLY_LEAVE),
        ("17:40", AttendanceStatus.NORMAL),  # 유예 20분의 경계
        ("17:59", AttendanceStatus.NORMAL),
        ("18:00", AttendanceStatus.NORMAL),
        ("19:00", AttendanceStatus.NORMAL),  # 퇴근을 찍었으면 늦어도 퇴근이다
        ("22:00", AttendanceStatus.NORMAL),
    ],
)
def test_퇴근_시각별_판정(check_out, expected):
    assert judge(rec("09:00", check_out)) is expected


def test_조기퇴근_유예는_20분이다():
    """1분만 일러도 조기퇴근으로 부르면 정리하고 나오는 사람이 매일 걸린다."""
    assert EARLY_LEAVE_GRACE_MIN == 20
    assert judge(rec("09:00", "17:39")) is AttendanceStatus.EARLY_LEAVE
    assert judge(rec("09:00", "17:40")) is AttendanceStatus.NORMAL


# ── 지각 ──────────────────────────────────────────────────────────────

def test_정각까지는_지각이_아니다():
    assert judge(rec("09:00", "18:00")) is AttendanceStatus.NORMAL
    assert judge(rec("09:01", "18:00")) is AttendanceStatus.LATE


def test_지각과_조기퇴근이_겹치면_따로_있다():
    assert judge(rec("09:30", "17:00")) is AttendanceStatus.LATE_AND_EARLY


def test_가입한_날은_지각도_조기퇴근도_안_매긴다():
    """계정을 만들면서 그 자리에서 바코드를 댄다 — 그게 근무 시작보다 늦으면
    **전원이 첫날부터 지각**으로 찍혔다 (8/12 가입자 전원, 실제 발생)."""
    first = day(WORKDAY)
    assert judge(rec("11:00", "16:00"), joined=first) is AttendanceStatus.NORMAL
    # 다음 날부터는 그대로 매긴다
    assert judge(rec("11:00", "16:00"), joined=day("2026-08-12")) is AttendanceStatus.LATE_AND_EARLY


# ── 아직 안 간 사람 — 시계로 바뀐다 ────────────────────────────────────

@pytest.mark.parametrize(
    "now, expected",
    [
        ("10:00", AttendanceStatus.IN_PROGRESS),
        ("17:00", AttendanceStatus.IN_PROGRESS),
        ("18:00", AttendanceStatus.IN_PROGRESS),
        ("18:59", AttendanceStatus.IN_PROGRESS),
        ("19:00", AttendanceStatus.OVERTIME),  # 퇴근시간 + 1시간
        ("23:00", AttendanceStatus.OVERTIME),
    ],
)
def test_퇴근을_안_찍으면_시계가_판정을_바꾼다(now, expected):
    """퇴근 스캔을 기다리면 **밤 11시까지 남아 있는 사람이 그냥 '출근'** 이다."""
    a = rec("09:00", None)
    assert _attendance_status(a, *SHIFT, at(WORKDAY, now)) is expected


def test_야근_문턱은_한_시간이다():
    """근무 외 출근 자동 점수와 **같은 값**이다 — 점수 받는 날과 화면에
    야근으로 뜨는 날이 갈리면 헷갈린다."""
    assert OVERTIME_THRESHOLD_MIN == 60


def test_지난_날짜에_퇴근이_없으면_퇴근누락이다():
    """야근은 '지금 센터에 있는 사람' 이라 지난 날짜에는 안 뜬다."""
    a = rec("09:00", None)
    assert _attendance_status(a, *SHIFT, at("2026-08-14", "10:00")) is AttendanceStatus.NO_CHECKOUT


# ── 자정을 넘긴 퇴근 ──────────────────────────────────────────────────

def test_자정을_넘겨_찍어도_조기퇴근이_아니다():
    """하루를 안 더하면 01:30 이 0시 기준 90분이라 **조기퇴근**으로 잡힌다."""
    a = rec("09:00", "01:30", out_day="2026-08-14")
    assert judge(a, now=at("2026-08-14", "09:00")) is AttendanceStatus.NORMAL


def test_자정을_넘겨_찍은_지각자는_지각으로_남는다():
    a = rec("09:30", "01:30", out_day="2026-08-14")
    assert judge(a, now=at("2026-08-14", "09:00")) is AttendanceStatus.LATE


# ── 판정할 수 없는 경우 ───────────────────────────────────────────────

def test_출근_기록이_없으면_판정불가다():
    assert judge(rec(None)) is AttendanceStatus.UNKNOWN


def test_근무시간을_설정_안_했으면_판정불가다():
    """근무 요일·시간을 안 넣은 사람이 23명 중 19명이던 때가 있었다 —
    그 사람들을 결근이나 지각으로 부르면 안 된다."""
    a = rec("09:00", "18:00")
    assert _attendance_status(a, None, None, NOW) is AttendanceStatus.UNKNOWN
    assert _attendance_status(a, "09:00", None, NOW) is AttendanceStatus.UNKNOWN
