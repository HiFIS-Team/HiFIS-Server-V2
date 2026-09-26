"""그 사람이 **그날 나오는 날인가** — 판정을 한 곳에 모은다 (2026-09-21).

생일을 휴무로 치기로 하면서 만들었다. 같은 질문을 **여섯 곳**이 따로
하고 있었고, 전부 `day.isoweekday() not in work_days` 를 손으로 적어
두어서 한 곳만 고치면 갈렸다.

| 자리 | 무엇에 쓰나 |
|---|---|
| `services/my_tasks.is_workday` | 개인 업무가 그날 서는가 · 이월 · 확정 누락 |
| `attendance` 개인 달력 | `휴무` 냐 `결근` 이냐 |
| `attendance` 전사 달력 | 같음 |
| `workers/absence_alerts` | 결근 알림을 보내나 |
| `employees` 명단 | 오늘 상태 칸 |
| `home` 홈 화면 | 같음 |

## 생일은 휴무다 (2026-09-21 대표 요청)

그날은 **결근이 안 찍히고 개인 업무도 안 선다.** 나와서 일하면 근태
기록이 남아 평소처럼 판정된다 — 쉬라고 여는 것이지 못 오게 막는 게 아니다.

**해마다 돈다.** 저장된 값은 연도가 있는 `date` 지만 월·일만 본다.

**급여는 안 건드린다.** 알바 시급은 `payroll._work_day_count` 가 따로
세는데, 거기까지 빼면 생일에 쉬었다고 그달 급여가 준다 — 그건 혜택이 아니라
벌이다. 생일 휴무는 '안 나와도 결근이 아니다' 까지다.

## 공휴일도 휴무다 (2026-09-26)

생일과 **같은 자리에서** 뺀다 — 결근이 안 찍히고 개인 업무도 안 선다.
판정은 `services/holidays.is_holiday` (법정 공휴일 + 대체공휴일 + 회사 휴무일).
2026 추석에 전원이 결근·누락으로 찍힐 뻔해서 휴가를 손으로 넣었던 자리다
(backend-gap 88). 급여는 생일과 같은 이유로 안 건드린다.

## 2월 29일

그해에 그 날짜가 없으면 그냥 안 걸린다. 28일로 당기지 않는다 — 당기면
평년마다 2월 28일이 온 센터의 휴무가 되는데 아무도 그걸 정한 적이 없다.
"""

from datetime import date

from app.models.staff.employee import Employee
from app.services.holidays import is_holiday


def is_birthday(employee: Employee | None, day: date) -> bool:
    """그날이 이 사람 생일인가 — **월·일만 본다** (연도는 저장용이다)."""
    born = employee.birthday if employee else None
    return born is not None and (born.month, born.day) == (day.month, day.day)


def rests_on(employee: Employee | None, day: date) -> bool:
    """근무 요일과 상관없이 쉬는 날인가 — 생일이거나 공휴일."""
    return is_birthday(employee, day) or is_holiday(day)


def works_on(employee: Employee | None, day: date) -> bool:
    """그날 나오는 날인가 — 근무 요일이면서 쉬는 날([rests_on])이 아니어야 한다.

    **근무 요일을 안 정했으면 나오는 날로 본다.** 안 정한 사람을 쉬는
    사람으로 치면 결근·누락이 통째로 사라진다 (근무 요일을 아직 안 넣은
    사람이 많다 — backend-gap 69).
    """
    if rests_on(employee, day):
        return False
    days = (employee.work_days if employee else None) or []
    return not days or day.isoweekday() in days
