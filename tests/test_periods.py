"""기간(period) 경계 — **한 달은 KST 로 자른다.**

2026-09-01 에 실제로 터진 자리다. 민중기·유찬빈이 기존 회원을 소급 입력하면서
구매일을 `08-01 00:00` 으로 넣었는데, 그게 UTC 로는 `07-31 15:00` 이라
`period_range("2026-08")` 창에 안 들어왔다 — **8월 매출 1,925만원이 통째로
7월 랭킹에 잡혔고, 정작 본인 화면에는 0원이었다.**

깨지면 고치기 전에 의도한 변경인지 먼저 확인한다. 이 창 하나를 랭킹 · 급여 ·
세션 집계 · 근태 달력 · 등록권 목록이 같이 쓴다.
"""

from datetime import datetime, timezone

import pytest

from app.core.periods import KST, current_period, period_range

UTC = timezone.utc


def test_한_달은_KST_자정에_시작하고_끝난다():
    start, end = period_range("2026-08")
    assert start.astimezone(KST) == datetime(2026, 8, 1, tzinfo=KST)
    assert end.astimezone(KST) == datetime(2026, 9, 1, tzinfo=KST)
    # UTC 로는 아홉 시간 앞이다 — 저장된 timestamptz 와 그대로 비교된다
    assert start.astimezone(UTC) == datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 8, 31, 15, 0, tzinfo=UTC)


def test_KST_1일_자정_기록이_그_달에_든다():
    """터졌던 그 값 그대로 — `08-01 00:00 KST` 는 **8월**이다."""
    bought = datetime(2026, 8, 1, tzinfo=KST)
    jul_s, jul_e = period_range("2026-07")
    aug_s, aug_e = period_range("2026-08")
    assert not (jul_s <= bought < jul_e)
    assert aug_s <= bought < aug_e


def test_KST_말일_끝자락도_그_달에_든다():
    late = datetime(2026, 8, 31, 23, 59, tzinfo=KST)
    aug_s, aug_e = period_range("2026-08")
    sep_s, sep_e = period_range("2026-09")
    assert aug_s <= late < aug_e
    assert not (sep_s <= late < sep_e)


def test_이웃한_달이_빈틈없이_이어진다():
    assert period_range("2026-08")[1] == period_range("2026-09")[0]
    assert period_range("2026-12")[1] == period_range("2027-01")[0]


#: `"2026-1"` 은 원래 통과한다 (한 자리 달을 받아 준다) — 여기서 좁히지 않는다
@pytest.mark.parametrize("period", ["2026", "abc", "2026-13-01", ""])
def test_형식이_틀리면_400(period):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        period_range(period)


def test_날짜_칸에_쓸_때는_KST_달력_날짜다():
    """`Attendance.date` 는 DATE 라 `.date()` 로 쓴다 — KST 날짜여야 한다."""
    start, end = period_range("2026-08")
    assert start.date().isoformat() == "2026-08-01"
    assert end.date().isoformat() == "2026-09-01"


def test_현재_기간은_KST_기준이다(monkeypatch):
    """9/1 새벽 0~9시(KST)에 UTC 로 재면 8월이 나온다 — 그러면 안 된다."""
    import app.core.periods as periods

    fixed = datetime(2026, 9, 1, 8, 0, tzinfo=KST)
    monkeypatch.setattr(periods, "now_kst", lambda: fixed)
    assert current_period() == "2026-09"
    assert fixed.astimezone(UTC).strftime("%Y-%m") == "2026-08"  # 옛 동작


def test_익월_지급형_급여_창도_KST다():
    from app.services.payroll import payroll_window

    class _P:
        day = 10
        next_month = True

    start, end = payroll_window("2026-10", _P())
    assert start.astimezone(KST) == datetime(2026, 9, 10, tzinfo=KST)
    assert end.astimezone(KST) == datetime(2026, 10, 10, tzinfo=KST)
    # 9/10 자정에 등록한 건이 창 안에 들어야 한다
    assert start <= datetime(2026, 9, 10, tzinfo=KST) < end
    assert not (start <= datetime(2026, 9, 9, 23, 59, tzinfo=KST) < end)


def test_말일형은_period_range_와_같다():
    from app.services.payroll import payroll_window

    assert payroll_window("2026-08", None) == period_range("2026-08")
