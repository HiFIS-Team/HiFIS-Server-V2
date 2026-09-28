from datetime import date

from app.services.monthly_goals import first_monday


def test_first_monday():
    assert first_monday(date(2026, 9, 15)) == date(2026, 9, 7)   # 1일이 화요일
    assert first_monday(date(2026, 6, 1)) == date(2026, 6, 1)    # 1일이 월요일
    assert first_monday(date(2026, 11, 30)) == date(2026, 11, 2)  # 1일이 일요일


def test_can_check_this_and_last_month():
    from app.services.monthly_goals import can_check

    today = date(2026, 1, 5)
    assert can_check("2026-01", today)
    assert can_check("2025-12", today)  # 해가 바뀌어도 지난 달
    assert not can_check("2025-11", today)
