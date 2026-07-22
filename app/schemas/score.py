"""ScoreEvent DTO — CLAUDE.md §4.1."""

from datetime import datetime

from app.enums import ScoreCategory
from app.schemas.base import CamelModel


class ScoreCreate(CamelModel):
    employee_id: str
    category: ScoreCategory = ScoreCategory.OPERATOR  # 운영자 직접 부여/감점
    points: int  # 음수 = 감점/취소
    reason: str | None = None
    period: str | None = None  # 없으면 현재 기간


class ScoreEventOut(CamelModel):
    id: str
    employee_id: str
    branch_id: str
    category: ScoreCategory
    points: int
    reason: str | None = None
    source_ref_id: str | None = None
    period: str
    created_by_id: str
    created_at: datetime


class RankingItem(CamelModel):
    rank: int
    employee_id: str
    name: str
    points: int


class ScoreSummary(CamelModel):
    employee_id: str
    period: str | None = None
    total: int
    by_category: dict[str, int]
