"""급여 주기·지급일 — `backend-gap.md` 76번의 검증표를 옮긴 것이다.

문서에 이렇게 적혀 있다.

    화순 TRAINER   2026-09: 09-01~09-30  지급 09-30  O    (2026-08 은 막힘)
    첨단 TRAINER   2026-10: 09-10~10-09  지급 10-10  O    (2026-09 도 막힘)
    첨단 FC        2026-09: 09-01~09-30  지급 09-30  O
    동광주 점장     2026-10: 09-10~10-09  지급 10-10  O

**돈이 걸린 계산이다.** 여기가 틀리면 어느 달 실적이 어느 명세서에 들어가는지가
어긋나고, 그건 실제로 준 돈과 안 맞는다는 뜻이다.
"""


import pytest

from app.models.payroll.payday_policy import PaydayPolicy
from app.services.payroll import (
    compute_payday,
    payday_window,
    payroll_month_of,
    payroll_started,
    payroll_window,
)

from tests.helpers import day


def policy(*, dayno: int | None, next_month: bool, starts_on: str = "1970-01-01") -> PaydayPolicy:
    return PaydayPolicy(day=dayno, next_month=next_month, starts_on=day(starts_on))


# 실제 운영에 깔린 두 규칙
MALIL = policy(dayno=None, next_month=False)          # 말일형 — 화순 전원 · FC
IKWOL10 = policy(dayno=10, next_month=True)           # 익월 10일형 — 동광주·첨단 트레이너


# ── 지급일 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ym, expected",
    [
        ("2026-09", "2026-09-30"),
        ("2026-02", "2026-02-28"),  # 평년
        ("2024-02", "2024-02-29"),  # 윤년 — 말일을 세는 자리라 걸린다
        ("2026-12", "2026-12-31"),
    ],
)
def test_말일형은_그_달_말일에_준다(ym, expected):
    assert compute_payday(ym, MALIL) == day(expected)


def test_익월_10일형은_그_달_10일에_준다():
    assert compute_payday("2026-10", IKWOL10) == day("2026-10-10")


def test_규칙이_없으면_말일이다():
    """아직 규칙이 안 깔린 곳 — 예전 동작 그대로."""
    assert compute_payday("2026-09", None) == day("2026-09-30")


# ── 주기 창 — 어느 달 실적이 그 명세서에 드는가 ────────────────────────

def test_말일형_주기는_그_달_1일부터다():
    start, end = payroll_window("2026-09", MALIL)
    assert (start.date(), end.date()) == (day("2026-09-01"), day("2026-10-01"))


def test_익월_10일형_주기는_전월_10일부터다():
    """9/10 에 받는 돈이 8/10~9/9 것이라는 뜻이다."""
    start, end = payroll_window("2026-10", IKWOL10)
    assert (start.date(), end.date()) == (day("2026-09-10"), day("2026-10-10"))


def test_연말을_넘어가도_전월을_제대로_짚는다():
    start, end = payroll_window("2026-01", IKWOL10)
    assert (start.date(), end.date()) == (day("2025-12-10"), day("2026-01-10"))


def test_주기가_겹치지_않고_이어진다():
    """빈틈이나 겹침이 있으면 어떤 날의 실적이 두 번 세어지거나 사라진다."""
    for ym, nxt in (("2026-09", "2026-10"), ("2026-10", "2026-11"), ("2026-12", "2027-01")):
        _, end = payroll_window(ym, IKWOL10)
        start2, _ = payroll_window(nxt, IKWOL10)
        assert end == start2, f"{ym} 끝과 {nxt} 시작이 안 맞는다"


# ── 개시 가드 — 앱을 켜기 전 실적은 급여로 안 잡는다 ───────────────────

def test_개시일_전_주기는_명세서를_못_만든다():
    """앱을 켜기 전 실적까지 급여로 잡으면 **안 준 돈이 생긴 것처럼** 보인다."""
    hwasun = policy(dayno=None, next_month=False, starts_on="2026-09-01")
    assert payroll_started("2026-08", hwasun) is False
    assert payroll_started("2026-09", hwasun) is True


def test_익월형은_개시일_때문에_한_달_더_막힌다():
    """첨단 트레이너는 2026-09 도 막힌다 — 그 주기가 8/10 부터라서다."""
    cheomdan = policy(dayno=10, next_month=True, starts_on="2026-09-10")
    assert payroll_started("2026-09", cheomdan) is False  # 08-10 ~ 09-09
    assert payroll_started("2026-10", cheomdan) is True   # 09-10 ~ 10-09


def test_규칙이_없으면_안_막는다():
    assert payroll_started("2020-01", None) is True


# ── 오늘이 속한 주기 ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "today, expected",
    [
        ("2026-09-09", "2026-09"),  # 10일 전 — 아직 9월 주기
        ("2026-09-10", "2026-10"),  # 10일 — 10월 주기의 첫날
        ("2026-09-30", "2026-10"),
        ("2026-12-10", "2027-01"),  # 해를 넘긴다
    ],
)
def test_익월형은_10일에_다음_달로_넘어간다(today, expected):
    assert payroll_month_of(day(today), IKWOL10) == expected


def test_말일형은_오늘_그_달이다():
    assert payroll_month_of(day("2026-09-09"), MALIL) == "2026-09"
    assert payroll_month_of(day("2026-09-30"), MALIL) == "2026-09"


# ── 신청 창 — 지급일 당일만 ───────────────────────────────────────────

def test_신청은_지급일_당일에만_열린다():
    assert payday_window("2026-09", day("2026-09-29"), MALIL)["is_open"] is False
    assert payday_window("2026-09", day("2026-09-30"), MALIL)["is_open"] is True
    assert payday_window("2026-09", day("2026-10-01"), MALIL)["is_open"] is False
