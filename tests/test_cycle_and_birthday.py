"""도는 차례(주·월)와 생일 휴무 — **사람의 하루가 바뀌는 판정이다** (2026-09-21).

셋 다 DB 를 안 타는 순수 계산이라 여기서 본다.

| 무엇 | 왜 여기 있나 |
|---|---|
| `stands_on` | 그날 개인 업무가 서는가 — 틀리면 **없던 누락**이 난다 |
| `is_birthday` | 그날이 생일인가 — 해마다 돌아야 한다 |
| `works_on` | 나오는 날인가 — 결근·누락·달력이 다 이걸 본다 |

깨지면 고치기 전에 **의도한 변경인지 먼저 확인한다** — 사람 점수와 근태가 바뀐다.
"""

from datetime import date, datetime, timezone

from app.models.scoring.my_task import MyTask
from app.models.staff.employee import Employee
from app.services.my_tasks import stands_on
from app.services.workdays import is_birthday, works_on


def _task(*, weekdays=None, monthdays=None) -> MyTask:
    return MyTask(
        weekdays=weekdays if weekdays is not None else [1, 2, 3, 4, 5, 6, 7],
        monthdays=monthdays,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _person(*, work_days=None, birthday=None) -> Employee:
    return Employee(work_days=work_days, birthday=birthday)


# ── 주 단위 — 여태 하던 방식이 그대로여야 한다 ──────────────────────────


def test_요일_업무는_고른_요일에만_선다():
    task = _task(weekdays=[5])  # 금요일만
    assert stands_on(task, date(2026, 9, 18))  # 금
    assert not stands_on(task, date(2026, 9, 17))  # 목


def test_매일_업무는_이레_다_선다():
    task = _task()
    for day in range(14, 21):  # 2026-09-14(월) ~ 20(일)
        assert stands_on(task, date(2026, 9, day))


# ── 월 단위 (2026-09-21) ────────────────────────────────────────────────


def test_월_단위는_요일을_안_본다():
    """날짜가 걸려 있으면 `weekdays` 는 무시한다 — 둘을 같이 걸지 않는다.

    만들 때 `weekdays` 를 매일로 채워 보내는데(컬럼이 NOT NULL 이다), 그걸
    같이 보면 월 단위 업무가 매일 서게 된다.
    """
    task = _task(weekdays=[1, 2, 3, 4, 5, 6, 7], monthdays=[1, 15])
    assert stands_on(task, date(2026, 9, 1))
    assert stands_on(task, date(2026, 9, 15))
    assert not stands_on(task, date(2026, 9, 2))
    assert not stands_on(task, date(2026, 9, 16))


def test_없는_날은_그_달에_안_선다():
    """31일짜리는 2월에 안 돈다 — **말일로 안 당긴다.**

    당기면 2월 28일에 서는데, 그날 제 차례인 다른 업무와 섞여서 왜 오늘
    섰는지가 화면에서 안 보인다.
    """
    task = _task(monthdays=[31])
    assert stands_on(task, date(2026, 1, 31))
    assert not stands_on(task, date(2026, 2, 28))
    assert not stands_on(task, date(2026, 4, 30))


def test_빈_날짜는_요일로_돌아간다():
    """`monthdays` 가 비면 월 단위가 아니다 — `None` 과 `[]` 가 같은 뜻이다."""
    for empty in (None, []):
        task = _task(weekdays=[5], monthdays=empty)
        assert stands_on(task, date(2026, 9, 18))  # 금
        assert not stands_on(task, date(2026, 9, 17))


# ── 생일 휴무 (2026-09-21) ──────────────────────────────────────────────


def test_생일은_해마다_돈다():
    """저장된 값은 연도가 있는 `date` 지만 **월·일만 본다.**"""
    person = _person(birthday=date(1995, 3, 14))
    assert is_birthday(person, date(2026, 3, 14))
    assert is_birthday(person, date(2030, 3, 14))
    assert not is_birthday(person, date(2026, 3, 15))


def test_생일을_안_넣었으면_안_걸린다():
    assert not is_birthday(_person(), date(2026, 3, 14))
    assert not is_birthday(None, date(2026, 3, 14))


def test_윤년_생일은_평년에_안_걸린다():
    """2월 29일은 그해에 없으면 그냥 넘어간다 — 28일로 안 당긴다."""
    person = _person(birthday=date(2024, 2, 29))
    assert is_birthday(person, date(2028, 2, 29))
    assert not is_birthday(person, date(2026, 2, 28))


def test_생일에는_나오는_날이_아니다():
    """근무 요일이어도 그날은 쉰다 — 결근·개인 업무 누락이 안 잡힌다."""
    person = _person(work_days=[1, 2, 3, 4, 5], birthday=date(1995, 9, 16))
    assert works_on(person, date(2026, 9, 15))  # 화 — 평소
    assert not works_on(person, date(2026, 9, 16))  # 수 — 생일


def test_근무_요일을_안_정했으면_나오는_날로_본다():
    """안 정한 사람을 쉬는 사람으로 치면 결근·누락이 통째로 사라진다.

    **생일은 그래도 뺀다** — 근무 요일과 따로 판단한다.
    """
    person = _person(birthday=date(1995, 9, 16))
    assert works_on(person, date(2026, 9, 19))  # 토요일도 근무일
    assert not works_on(person, date(2026, 9, 16))  # 생일만 쉰다
