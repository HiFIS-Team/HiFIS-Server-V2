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


# ── 만들기 전 날에는 서지 않는다 (2026-09-21) ────────────────────────────
#
# `due_tasks` 의 제 차례 목록에 만든 날 가드가 없어서, **오늘 만든 업무가
# 지난 근무일에도 서 있던 것으로 셈됐다.** 그날 안 한 것이 되어 없던 업무로
# 확정 누락(-10~-30)이 났다. `born_on(t) <= day` 가 그걸 막는다.
#
# 여기서는 그 가드가 읽는 값(`born_on`)을 본다 — UTC 로 셈하면 **KST 새벽에
# 만든 업무가 전날 생긴 것**이 되어 가드가 하루를 헛돈다.


def test_새벽에_만든_업무도_만든_날은_KST_기준이다():
    from datetime import datetime, timezone

    from app.models.scoring.my_task import MyTask
    from app.services.my_tasks import born_on

    # 2026-09-08 08:00 KST = 2026-09-07 23:00 UTC — `.date()` 로는 7일이 된다
    task = MyTask(created_at=datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc))
    assert task.created_at.date() == date(2026, 9, 7)  # 옛 셈
    assert born_on(task) == date(2026, 9, 8)  # KST 근무일

    # 저녁에 만든 것은 UTC 와 같은 날이다 (12:00 KST = 03:00 UTC)
    noon = MyTask(created_at=datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc))
    assert born_on(noon) == date(2026, 9, 8)

    # 만든 날보다 앞선 날에는 안 선다 — 가드가 쓰는 비교 그대로
    assert not born_on(task) <= date(2026, 9, 7)
    assert born_on(task) <= date(2026, 9, 8)
