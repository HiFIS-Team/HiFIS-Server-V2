"""SessionSign DTO — CLAUDE.md §3.3."""

from datetime import datetime

from app.enums import RegistrationType
from app.schemas.base import CamelModel, SignedUrl
from app.schemas.members.registration import RegistrationOut


class SessionSignCreate(CamelModel):
    registration_id: str
    #: 회원이 그린 서명 PNG(base64) — [skip_signature] 가 True 면 안 보낸다
    signature_base64: str | None = None
    performed_by_trainer_id: str | None = None  # 없으면 요청자(수행 트레이너)
    #: 싸인을 못 받고 회차만 올린다 (2026-09-05 요청)
    #:
    #: 회원이 먼저 가 버렸거나 서명을 받을 수 없는 자리가 있다. 누가 생략했는지는
    #: 서버가 `signature_skipped_by_id` 에 남긴다.
    skip_signature: bool = False


class SessionSignOut(CamelModel):
    id: str
    registration_id: str
    member_id: str
    performed_by_trainer_id: str
    session_no: int
    #: 서명 이미지 — 생략한 기록이면 비어 있다
    signature_url: SignedUrl | None = None
    signed_at: datetime
    #: 싸인 없이 채운 회차인가 — 아래 `signature_skipped_by_id` 가 차 있으면 True
    signature_skipped: bool = False
    signature_skipped_by_id: str | None = None
    #: 생략한 사람 이름 — 목록이 바로 그리려고 서버가 조인해 준다
    signature_skipped_by_name: str | None = None
    # 앱 기록 표시용 조인값(목록·생성 응답에서 서버가 채움) — "박서연 [신규] 12/20회차"
    member_name: str | None = None
    total_sessions: int | None = None
    registration_type: RegistrationType | None = None


class SessionSignResult(CamelModel):
    sign: SessionSignOut
    registration: RegistrationOut
