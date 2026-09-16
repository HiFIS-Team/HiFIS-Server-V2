"""개인 업무 누락 차감 — **쌓이고, 닷새 조용하면 처음으로 돌아간다** (2026-09-16).

2026-08-21 에는 `-20 고정`이었다. 그러면 늘 빠뜨리는 사람과 처음 빠뜨린
사람이 같은 값을 문다 — 지각 차감과 같은 이유로 누적으로 갈았다.

**리셋이 지각에는 없는 규칙이다.** 업무 누락은 매일 걸리는 일이라 리셋이
없으면 한 번 -30 에 닿은 사람은 그 뒤로 영영 -30 이고, 잘하기 시작해도
달라지는 것이 없어서 쌓아 올린 뜻이 사라진다.

깨지면 고치기 전에 **의도한 변경인지 먼저 확인한다** — 사람 점수가 바뀐다.
"""

from datetime import date

from app.models.staff.employee import Employee
from app.workers.my_task_miss_scan import (
    TASK_MISS_PENALTY,
    TASK_MISS_RESET_WORKDAYS,
    _workdays_between,
)


def _points(nth: int) -> int:
    """잡이 쓰는 것과 같은 식 — 마지막 칸을 넘으면 그 값이 계속 붙는다."""
    return TASK_MISS_PENALTY[min(nth, len(TASK_MISS_PENALTY)) - 1]


def test_쌓인다():
    assert [_points(n) for n in (1, 2, 3)] == [-10, -20, -30]


def test_마지막_칸을_넘으면_그대로다():
    assert _points(4) == _points(9) == TASK_MISS_PENALTY[-1]


def _person(work_days: list[int] | None) -> Employee:
    return Employee(work_days=work_days)


def test_근무일만_센다():
    """주 3일(월·수·금) 일하는 사람에게 달력 일주일은 근무일 셋이다."""
    person = _person([1, 3, 5])
    # 9/7(월) 과 9/14(월) 사이 — 9·11(수·금) + 다음 주 9·11 … 은 아니고
    # 사이에 드는 근무일은 9/9(수) · 9/11(금) 둘뿐이다
    assert _workdays_between(person, date(2026, 9, 7), date(2026, 9, 14), stop_at=9) == 2


def test_양끝은_안_센다():
    """두 누락 **사이**가 얼마나 비었나를 재는 것이라 누락한 날은 빼야 한다."""
    person = _person(None)
    assert _workdays_between(person, date(2026, 9, 1), date(2026, 9, 2), stop_at=9) == 0
    assert _workdays_between(person, date(2026, 9, 1), date(2026, 9, 3), stop_at=9) == 1


def test_근무_요일을_안_정했으면_모든_날이_근무일이다():
    """`is_workday` 와 같은 규칙 — 안 정한 사람을 쉬는 사람으로 치면 안 된다."""
    person = _person([])
    assert _workdays_between(person, date(2026, 9, 1), date(2026, 9, 10), stop_at=99) == 8


def test_문턱에_닿으면_거기서_멈춘다():
    """몇 달 전 누락과의 간격을 끝까지 셀 이유가 없다."""
    person = _person(None)
    got = _workdays_between(
        person, date(2026, 1, 1), date(2026, 12, 31), stop_at=TASK_MISS_RESET_WORKDAYS
    )
    assert got == TASK_MISS_RESET_WORKDAYS
