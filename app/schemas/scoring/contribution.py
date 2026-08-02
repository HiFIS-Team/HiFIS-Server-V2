"""ContributionGrant DTO — CLAUDE.md §4.4."""

from datetime import datetime

from pydantic import Field

from app.enums import ContribType
from app.schemas.base import CamelModel


class ContributionCreate(CamelModel):
    employee_id: str
    type: ContribType
    hours: int | None = Field(default=None, gt=0)  # EXTRA_WORK 필수
    reason: str


class ContributionGrantOut(CamelModel):
    id: str
    employee_id: str
    type: ContribType
    hours: int | None = None
    points: int
    reason: str
    granted_by_id: str
    created_at: datetime
