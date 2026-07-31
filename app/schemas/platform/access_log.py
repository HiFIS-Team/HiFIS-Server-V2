"""접속 로그 조회 DTO — 관리자 이상 접근 모니터링 (개인정보처리방침 §8)."""

from datetime import datetime

from app.enums import AccessEvent
from app.schemas.base import CamelModel


class AccessLogOut(CamelModel):
    id: str
    employee_id: str | None = None
    email: str | None = None
    event: AccessEvent
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime
