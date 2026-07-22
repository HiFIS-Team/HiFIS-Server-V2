"""ScoreEvent DTO — CLAUDE.md §4.1."""

from datetime import datetime

from app.enums import ScoreCategory
from app.schemas.base import CamelModel


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
