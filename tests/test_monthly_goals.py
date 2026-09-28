from datetime import date

from app.services.monthly_goals import first_monday


def test_first_monday():
    assert first_monday(date(2026, 9, 15)) == date(2026, 9, 7)   # 1일이 화요일
    assert first_monday(date(2026, 6, 1)) == date(2026, 6, 1)    # 1일이 월요일
    assert first_monday(date(2026, 11, 30)) == date(2026, 11, 2)  # 1일이 일요일
