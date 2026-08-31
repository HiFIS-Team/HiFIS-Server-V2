"""알바 시급 계산 — `backend-gap.md` 75번의 **검산된 금액**을 옮긴 것이다.

문서에 이렇게 적혀 있다.

    평일 09~18   21일 × 540분 = 189.0h → 1,950,480원   (검산 일치)
    주말만 10~15 10일 × 300분 =  50.0h →   516,000원
    야간 22~06   21일 × 480분 = 168.0h → 1,733,760원
    요일 미설정  NO_SCHEDULE 로 막힘

계산 근거는 **출퇴근 스캔이 아니라 본인이 설정한 근무시간**이다 —
스캔을 빼먹어도 급여가 비지 않는다.
"""


import pytest

from app.models.staff.employee import Employee
from app.services.payroll import _shift_minutes, _work_day_count

from tests.helpers import at

WAGE = 10_320  # 마이그레이션이 심은 전사 시급 (최저임금은 해마다 바뀐다)


def worker(start: str | None, end: str | None, days: list[int] | None) -> Employee:
    return Employee(shift_start=start, shift_end=end, work_days=days)


def pay(minutes_per_day: int, day_count: int) -> int:
    """문서가 쓴 식 그대로 — 하루 분 × 근무일수 ÷ 60 × 시급"""
    return round(minutes_per_day * day_count / 60 * WAGE)


# ── 하루 근무 분 ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "start, end, expected",
    [
        ("09:00", "18:00", 540),
        ("10:00", "15:00", 300),
        ("22:00", "06:00", 480),  # 자정을 넘긴다
        ("00:00", "24:00", 1440),
    ],
)
def test_하루_근무_분(start, end, expected):
    assert _shift_minutes(worker(start, end, [1])) == expected


def test_휴게시간을_빼지_않는다():
    """09~18 이면 9시간을 다 준다 (2026-08-05 대표 결정).

    근로기준법은 8시간 초과 시 1시간을 무급 휴게로 두지만, **설정한 시간
    그대로 주기로 정했다** — 월 22만원 차이라 물어보고 정한 값이다.
    """
    assert _shift_minutes(worker("09:00", "18:00", [1])) == 540  # 480 이 아니다


def test_근무시간을_설정_안_했으면_0분이다():
    """0 을 그냥 쓰면 안 된다 — 위에서 NO_SCHEDULE 로 막는 근거다."""
    assert _shift_minutes(worker(None, "18:00", [1])) == 0
    assert _shift_minutes(worker("09:00", None, [1])) == 0


# ── 주기 안의 근무일 수 ───────────────────────────────────────────────

def test_평일만_일하면_2026년_9월에_22일이다():
    """9/1(화) ~ 9/30(수) 사이의 월~금."""
    n = _work_day_count(worker("09:00", "18:00", [1, 2, 3, 4, 5]),
                        at("2026-09-01", "00:00"), at("2026-10-01", "00:00"))
    assert n == 22


def test_주말만_일하면_토일만_센다():
    n = _work_day_count(worker("10:00", "15:00", [6, 7]),
                        at("2026-09-01", "00:00"), at("2026-10-01", "00:00"))
    assert n == 8  # 9월의 토·일


def test_끝날은_안_센다():
    """`[start, end)` 라 마지막 날은 다음 주기 것이다 — 안 그러면 하루가 두 번 계산된다."""
    mon_only = worker("09:00", "18:00", [1])
    # 9/7 은 월요일. 9/7~9/8 이면 하루, 9/7~9/7 이면 0일
    assert _work_day_count(mon_only, at("2026-09-07", "00:00"), at("2026-09-08", "00:00")) == 1
    assert _work_day_count(mon_only, at("2026-09-07", "00:00"), at("2026-09-07", "00:00")) == 0


def test_익월_10일형_주기도_그대로_센다():
    """달력 월이 아니라 주기로 센다 — 8/10~9/9 가 한 달치다.

    **같은 사람이라도 주기에 따라 근무일 수가 다르다** (9월 22일 · 8/10~9/9 23일).
    그래서 달력 월로 세면 어느 달은 하루치가 통째로 어긋난다.
    """
    n = _work_day_count(worker("09:00", "18:00", [1, 2, 3, 4, 5]),
                        at("2026-08-10", "00:00"), at("2026-09-10", "00:00"))
    assert n == 23


def test_근무_요일을_설정_안_했으면_0일이다():
    """조용히 0원 명세서를 만들면 **안 준 게 아니라 0원을 준 것**이 된다 —
    위에서 NO_SCHEDULE 로 막는 근거가 이 0 이다."""
    assert _work_day_count(worker("09:00", "18:00", None),
                           at("2026-09-01", "00:00"), at("2026-10-01", "00:00")) == 0
    assert _work_day_count(worker("09:00", "18:00", []),
                           at("2026-09-01", "00:00"), at("2026-10-01", "00:00")) == 0


# ── 문서의 검산 금액 ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "start, end, days, day_count, minutes, expected_won",
    [
        ("09:00", "18:00", [1, 2, 3, 4, 5], 21, 540, 1_950_480),
        ("10:00", "15:00", [6, 7],          10, 300,   516_000),
        ("22:00", "06:00", [1, 2, 3, 4, 5], 21, 480, 1_733_760),
    ],
)
def test_문서에_적힌_금액이_그대로_나온다(start, end, days, day_count, minutes, expected_won):
    assert _shift_minutes(worker(start, end, days)) == minutes
    assert pay(minutes, day_count) == expected_won
