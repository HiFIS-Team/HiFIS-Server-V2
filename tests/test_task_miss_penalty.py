"""개인 업무 누락 차감 — **빠뜨린 항목 수로 매긴다** (2026-09-18 대표 결정).

하루치 기본 -20 에 항목이 하나 늘 때마다 -10 이 더 붙는다.

2026-09-16 에는 '며칠째 누락이냐' 로 쌓았다(-10/-20/-30 + 5근무일 리셋).
이틀 만에 걷어냈다 — 축이 둘이 되면 같은 3개를 빠뜨려도 날마다 값이 달라져서
**직원이 자기 점수를 미리 셀 수가 없다.**

깨지면 고치기 전에 **의도한 변경인지 먼저 확인한다** — 사람 점수가 바뀐다.
"""

from datetime import date

import pytest

from app.workers.my_task_miss_scan import (
    TASK_MISS_BASE,
    TASK_MISS_PER_TASK,
    task_miss_points,
)


def test_하나만_빠뜨리면_기본값이다():
    assert task_miss_points(1) == TASK_MISS_BASE == -20


@pytest.mark.parametrize(
    "count,expected",
    [(1, -20), (2, -30), (3, -40), (5, -60), (7, -80), (9, -100)],
)
def test_대표가_말한_값이_그대로_나온다(count: int, expected: int):
    """3개면 `처음 하나 -20 · 나머지 둘 -10씩` = -40 (2026-09-18)"""
    assert task_miss_points(count) == expected


def test_항목이_하나_늘_때마다_같은_값이_붙는다():
    for n in range(1, 20):
        assert task_miss_points(n + 1) - task_miss_points(n) == TASK_MISS_PER_TASK


def test_늘_음수다():
    """부호가 뒤집히면 누락이 점수를 **주는** 일이 된다"""
    assert all(task_miss_points(n) < 0 for n in range(0, 50))


def test_상한이_없다():
    """많이 빠뜨릴수록 계속 무거워진다 — 어디서 멎지 않는다"""
    assert task_miss_points(30) == -20 - 10 * 29


def test_0개여도_터지지_않는다():
    """누락 줄 자체가 안 생기는 값이지만, 와도 기본값만 문다"""
    assert task_miss_points(0) == TASK_MISS_BASE


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
