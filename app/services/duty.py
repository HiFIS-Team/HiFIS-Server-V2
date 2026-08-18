"""당직 — 토·일·공휴일의 근무 시간 (2026-08-18 대표 결정).

**이 날들은 사람마다 정해진 근무시간이 없다.** 당직이라 몇 명이 나눠 서는데
누가 어느 칸을 서는지가 시스템에 없다. 그래서 판정을 이렇게 나눈다.

| | 평일 | 토·일·공휴일 |
|---|---|---|
| 기준 시각 | 본인이 설정한 근무시간 | **아래 당직 시간** |
| 지각·조기퇴근·야근 | 매긴다 | **안 매긴다** — 스캔된 대로 출근/퇴근만 |
| 결근 | 근무 요일이면 찍는다 | **근무 요일이면 찍는다** (당직 종료 시각 기준) |
| 근무외출근 점수 | 본인 시간 ±1시간 | 당직 시간 ±1시간 |

**결근은 그대로 찍는다.** 본인 근무 요일에 들어 있으면 나와야 하는 날이고,
안 나왔으면 결근이 맞다. 다만 몇 시에 왔는지로 지각·조퇴를 매기지는 않는다 —
당직은 시간을 나눠 서서 **언제 오는 게 맞는지가 사람마다 다르기** 때문이다.

화순 토요일만 다르다 — 09~18 을 세 시간씩 세 명이 나눠 선다. 나눠 서는 칸까지는
안 담는다 (누가 어느 칸인지가 없으므로). **여는 시각과 닫는 시각만** 본다.
"""

from __future__ import annotations

from datetime import date

from app.services.holidays import is_holiday

#: 대부분의 당직 — 공휴일·일요일 전 지점, 토요일도 화순 말고는 이 시간이다
DUTY_DEFAULT: tuple[str, str] = ("11:00", "19:00")

#: 토요일만 지점마다 다르다 (지점 **이름** 기준 — id 는 환경마다 달라진다)
SATURDAY_BY_BRANCH: dict[str, tuple[str, str]] = {
    "화순": ("09:00", "18:00"),
}

_SATURDAY = 6


def is_duty_day(day: date) -> bool:
    """당직으로 도는 날인가 — 토·일·공휴일."""
    return day.isoweekday() >= _SATURDAY or is_holiday(day)


def duty_hours(day: date, branch_name: str | None = None) -> tuple[str, str] | None:
    """그날 당직 시간 `("11:00", "19:00")` — 당직일이 아니면 None.

    **공휴일이 토요일과 겹치면 공휴일 쪽(11~19)이 이긴다.** 공휴일은 전 지점이
    같은 시간이라고 정했으므로 지점별 토요일 규칙보다 앞선다.

    [branch_name] 을 안 주면 기본 시간으로 떨어진다 — 토요일 화순의 여는 시각만
    어긋나고(09시 대신 11시) 지각·조퇴를 어차피 안 매기므로 판정은 같다.
    점수와 결근 시각 계산에만 영향이 있다.
    """
    if not is_duty_day(day):
        return None
    if day.isoweekday() == _SATURDAY and not is_holiday(day):
        return SATURDAY_BY_BRANCH.get(branch_name or "", DUTY_DEFAULT)
    return DUTY_DEFAULT
