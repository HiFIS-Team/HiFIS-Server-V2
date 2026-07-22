"""기간(period, "YYYY-MM") 유틸 — 점수/매출 집계 공통."""

from datetime import datetime, timezone

from fastapi import HTTPException


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def period_range(period: str) -> tuple[datetime, datetime]:
    """"2026-07" → [해당 월 시작, 다음 월 시작) UTC."""
    try:
        year, month = (int(x) for x in period.split("-"))
        start = datetime(year, month, 1, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise HTTPException(400, detail={"code": "INVALID_PERIOD", "message": "period 형식은 YYYY-MM 입니다"})
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end
