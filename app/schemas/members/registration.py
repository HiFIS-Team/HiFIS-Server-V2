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
    #: 결제한 날 — 안 주면 지금. **기존 회원은 실제 결제일을 넣는다.**
    #: 매출 랭킹이 이 값을 보므로(`ranking_board.py`) 지난 달 결제는
    #: 이번 달 실적에 안 잡힌다.
    purchased_at: datetime | None = None
    #: 이미 받은 회차 — 앱을 켜기 전에 쓴 만큼. 안 주면 0 (옛 앱과 같다).
    #: 총 회차에 닿으면 상태가 `EXPIRED` 로 들어간다.
    used_sessions: int = Field(default=0, ge=0)


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
