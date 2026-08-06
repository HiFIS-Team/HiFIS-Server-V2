"""KindnessSurvey DTO — CLAUDE.md §4.5."""

from datetime import datetime

from app.enums import ComplaintStatus
from app.schemas.base import CamelModel


class KindnessSurveyWebhook(CamelModel):
    motivation: str
    praised_employee_id: str
    praise_comment: str
    improvement: str | None = None
    member_name: str
    member_phone: str
    consent: bool


class ComplaintStatusUpdate(CamelModel):
    status: ComplaintStatus


class KindnessSurveyOut(CamelModel):
    id: str
    motivation: str
    praised_employee_id: str
    praise_comment: str
    improvement: str | None = None
    member_name: str
    member_phone: str
    consent: bool
    submitted_at: datetime
    # 컴플레인 처리 — `improvement` 가 적힌 설문에서만 의미가 있다
    improvement_status: ComplaintStatus = ComplaintStatus.PENDING
    resolved_at: datetime | None = None
    resolved_by_id: str | None = None
