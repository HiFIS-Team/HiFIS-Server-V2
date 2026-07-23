"""SessionSign DTO — CLAUDE.md §3.3."""

from datetime import datetime

from app.schemas.base import CamelModel
from app.schemas.sales.registration import RegistrationOut


class SessionSignCreate(CamelModel):
    registration_id: str
    signature_base64: str
    performed_by_trainer_id: str | None = None  # 없으면 요청자(수행 트레이너)


class SessionSignOut(CamelModel):
    id: str
    registration_id: str
    member_id: str
    performed_by_trainer_id: str
    session_no: int
    signature_url: str
    signed_at: datetime


class SessionSignResult(CamelModel):
    sign: SessionSignOut
    registration: RegistrationOut
