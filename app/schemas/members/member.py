"""Member DTO — CLAUDE.md §3.1."""

from datetime import datetime

from pydantic import Field

from app.enums import RegistrationType
from app.schemas.base import CamelModel
from app.schemas.members.registration import RegistrationOut


class MemberRegistrationInput(CamelModel):
    """회원 등록과 함께 발급할 첫 등록권(선택). 실무상 등록권 없는 회원은 없어 한 번에 받는다."""

    type: RegistrationType
    total_sessions: int = Field(gt=0)
    price_paid: int = Field(ge=0)
    session_unit_price: int = Field(ge=0)
    trainer_id: str | None = None  # 없으면 담당 트레이너(ownerTrainerId)
    purchased_at: datetime | None = None


class MemberCreate(CamelModel):
    name: str
    phone: str
    branch_id: str
    owner_trainer_id: str
    referrer_member_id: str | None = None
    memo: str | None = None
    registration: MemberRegistrationInput | None = None  # 있으면 회원+등록권을 한 트랜잭션으로


class MemberUpdate(CamelModel):
    name: str | None = None
    phone: str | None = None
    owner_trainer_id: str | None = None
    referrer_member_id: str | None = None
    memo: str | None = None


class MemberOut(CamelModel):
    id: str
    name: str
    phone: str
    branch_id: str
    owner_trainer_id: str
    referrer_member_id: str | None = None
    registered_at: datetime
    memo: str | None = None


class MemberCreateOut(MemberOut):
    """POST /members 응답 — 등록권을 함께 발급했으면 실어 준다(추가 필드, 하위호환)."""

    registration: RegistrationOut | None = None
