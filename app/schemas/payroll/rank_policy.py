"""RankPolicy DTO — CLAUDE.md §1."""

from datetime import datetime

from pydantic import Field

from app.enums import Rank
from app.schemas.base import CamelModel


class RankPolicyCreate(CamelModel):
    rank: Rank
    base_salary: int = Field(ge=0)
    new_rate: float = Field(ge=0)
    renewal_rate: float = Field(ge=0)
    branch_id: str | None = None  # null = 전사 기본
    effective_from: datetime


class RankPolicyOut(CamelModel):
    id: str
    rank: Rank
    base_salary: int
    new_rate: float
    renewal_rate: float
    branch_id: str | None = None
    effective_from: datetime
