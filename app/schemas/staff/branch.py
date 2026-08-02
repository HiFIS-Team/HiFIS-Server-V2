"""Branch DTO — CLAUDE.md §2.1."""

from datetime import datetime
from typing import Literal

from app.schemas.base import CamelModel

BranchType = Literal["HQ", "BRANCH"]


class BranchCreate(CamelModel):
    name: str
    type: BranchType = "BRANCH"


class BranchUpdate(CamelModel):
    name: str | None = None
    type: BranchType | None = None


class BranchOut(CamelModel):
    id: str
    name: str
    type: BranchType
    created_at: datetime
