"""기간(period, "YYYY-MM") 유틸 — 점수/매출 집계 공통."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

# 한국 표준시 — 알림/리마인더의 벽시계 기준(급여 20시·출근 시간대·프로젝트 매일/매시).
KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def current_period() -> str:
    """지금이 몇 월인가 — **KST 기준이다.**

    UTC 로 재면 매월 1일 새벽 0~9시(KST)가 지난달로 잡힌다. 근무일·랭킹·급여가
    전부 KST 벽시계로 도는데 여기만 UTC 면, 그 아홉 시간에 쌓은 점수가 지난달
    원장에 들어간다 (실제로 겪었다).
    """
    return now_kst().strftime("%Y-%m")


def period_range(period: str) -> tuple[datetime, datetime]:
    """"2026-07" → [해당 월 1일 00:00, 다음 달 1일 00:00) **KST**.

    **UTC 로 자르면 안 된다.** 한 달이 `1일 09:00 ~ 다음달 1일 09:00 KST` 가
    되어, 그 아홉 시간에 걸친 기록이 이웃 달로 새어 나간다. 소급 입력한
    등록권의 구매일이 `08-01 00:00 KST`(= `07-31 15:00 UTC`)라 **8월 매출이
    통째로 7월에 잡힌 적이 있다** (2026-09-01, 두 사람 1,925만원).

    돌려주는 값은 KST 를 단 aware datetime 이라 timestamptz 비교에 그대로 쓴다.
    날짜 칸(`Attendance.date`)에 쓸 때는 `.date()` 가 곧 KST 달력 날짜다.
    """
    try:
        year, month = (int(x) for x in period.split("-"))
        start = datetime(year, month, 1, tzinfo=KST)
    except (ValueError, TypeError):
        raise HTTPException(400, detail={"code": "INVALID_PERIOD", "message": "period 형식은 YYYY-MM 입니다"})
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=KST)
    else:
        end = datetime(year, month + 1, 1, tzinfo=KST)
    return start, end
