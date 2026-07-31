"""SessionSign DTO — CLAUDE.md §3.3."""

from datetime import datetime

from app.enums import RegistrationType
from app.schemas.base import CamelModel, SignedUrl
from app.schemas.members.registration import RegistrationOut


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
    signature_url: SignedUrl
    signed_at: datetime
    # 앱 기록 표시용 조인값(목록·생성 응답에서 서버가 채움) — "박서연 [신규] 12/20회차"
    member_name: str | None = None
    total_sessions: int | None = None
    registration_type: RegistrationType | None = None


class SessionSignResult(CamelModel):
    sign: SessionSignOut
    registration: RegistrationOut
