"""프로젝트 리셋 — 완료를 처음으로 되돌린다 (2026-09-16 대표 결정).

조용한 되돌리기(`/reopen`)를 없애고 이 하나로 모았다. **길이 둘이면 어느
쪽을 눌러야 하는지를 매번 정해야 하고, 가벼운 쪽으로 기울면 벌점이 빈다.**

깨지면 고치기 전에 **의도한 변경인지 먼저 확인한다** — 사람 점수가 바뀐다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.projects.projects import (
    PM_POINT_GAP,
    PROJECT_MEMBER_POINTS,
    PROJECT_POINTS,
)

KST = timezone(timedelta(hours=9))


def test_PM_차이는_완료_기본_점수에서_나온다():
    """가점·감점이 쓰는 5는 **따로 정한 값이 아니다.**

    완료 기본 점수(PM 10 · 참여자 5)의 차이를 그대로 잇는다 — 둘을 따로 두면
    기본 점수를 고칠 때 한쪽만 바뀌어 규칙이 어긋난다.
    """
    assert PM_POINT_GAP == PROJECT_POINTS - PROJECT_MEMBER_POINTS == 5


def _penalty(base: int, *, is_pm: bool) -> int:
    """리셋 감점 — 라우터가 쓰는 것과 같은 식"""
    return -(base + (PM_POINT_GAP if is_pm else 0))


@pytest.mark.parametrize("base", [0, 10, 20, 100])
def test_PM_이_참여자보다_5점을_더_문다(base: int):
    assert _penalty(base, is_pm=True) == _penalty(base, is_pm=False) - PM_POINT_GAP


def _span_days(start: datetime, due: datetime) -> int:
    """리셋이 옮기는 기한 길이 — 라우터와 같은 식 (날 단위로 반올림)"""
    return max(round((due - start).total_seconds() / 86400), 0)


def test_기한은_길이를_그대로_옮긴다():
    """3일짜리는 리셋한 날부터 다시 3일이다."""
    span = _span_days(datetime(2026, 9, 1, tzinfo=KST), datetime(2026, 9, 4, tzinfo=KST))
    assert span == 3
    today = datetime(2026, 9, 16, tzinfo=KST)
    assert today + timedelta(days=span) == datetime(2026, 9, 19, tzinfo=KST)


def test_연장을_받았으면_늘어난_길이로_돈다():
    """처음 길이를 따로 저장해 두지 않았고, 연장은 대표가 승인해 준 것이다
    (2026-09-16 결정)."""
    assert _span_days(datetime(2026, 9, 1, tzinfo=KST), datetime(2026, 9, 8, tzinfo=KST)) == 7


def test_기한이_시작보다_이르면_0일이다():
    """음수 기한은 없다 — 손으로 밀어 넣은 값이 들어와도 과거로 안 간다."""
    assert _span_days(datetime(2026, 9, 8, tzinfo=KST), datetime(2026, 9, 1, tzinfo=KST)) == 0
