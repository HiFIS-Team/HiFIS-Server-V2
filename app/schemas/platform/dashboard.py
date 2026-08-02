"""대시보드 집계 DTO — ADMIN 요약 (CLAUDE.md §6.13)."""

from pydantic import Field

from app.schemas.base import CamelModel


class ScoreSummary(CamelModel):
    total: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)


class SalesSummary(CamelModel):
    total: int = 0          # Σ 결제액(원)
    count: int = 0          # 등록 건수
    new: int = 0            # 신규 매출 합
    renewal: int = 0        # 재등록 매출 합


class DashboardOut(CamelModel):
    branch_id: str | None = None  # None = 전체 지점
    period: str                   # "2026-07"
    headcount: int = 0            # 재직(ACTIVE) 직원 수
    scores: ScoreSummary = Field(default_factory=ScoreSummary)
    sales: SalesSummary = Field(default_factory=SalesSummary)
    checked_in_today: int = 0     # 오늘 출근 체크인 수
    leaves_pending: int = 0       # 대기중 휴가 신청 수
