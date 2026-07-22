"""Registration DTO — CLAUDE.md §3.2."""

from datetime import datetime

from pydantic import Field

from app.enums import RegistrationStatus, RegistrationType
from app.schemas.base import CamelModel


class RegistrationCreate(CamelModel):
    member_id: str
    trainer_id: str
    type: RegistrationType
    total_sessions: int = Field(gt=0)  # 회차 음수/0 방지 (§9.7)
    price_paid: int = Field(ge=0)
    session_unit_price: int = Field(ge=0)
    purchased_at: datetime | None = None


class RegistrationOut(CamelModel):
    id: str
    member_id: str
    trainer_id: str
    type: RegistrationType
    total_sessions: int
    used_sessions: int
    price_paid: int
    session_unit_price: int
    status: RegistrationStatus
    purchased_at: datetime
