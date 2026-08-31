"""테스트 공용 — **DB 도 픽스처도 안 쓴다.**

여기 있는 테스트는 전부 순수 계산이다. 서버를 띄우거나 Postgres 를 붙이지
않으므로 `pytest` 만 있으면 어디서나 돈다 (CI 도 그래서 한 줄이면 된다).

모델 객체(`Attendance` 등)는 세션에 넣기 전까지는 그냥 파이썬 객체라,
`Attendance(date=..., check_in=...)` 처럼 만들어 바로 넘길 수 있다.
"""

import datetime as dt

from app.core.periods import KST


def at(day: str, hm: str) -> dt.datetime:
    """`'2026-08-13' '09:00'` → KST 시각. 테스트를 표처럼 읽히게 하는 도우미."""
    y, m, d = (int(x) for x in day.split("-"))
    h, mi = (int(x) for x in hm.split(":"))
    return dt.datetime(y, m, d, h, mi, tzinfo=KST)


def day(value: str) -> dt.date:
    y, m, d = (int(x) for x in value.split("-"))
    return dt.date(y, m, d)
