"""KindnessSurvey DTO — CLAUDE.md §4.5."""

from datetime import datetime

from app.schemas.base import CamelModel


class KindnessSurveyWebhook(CamelModel):
    motivation: str
    praised_employee_id: str
    praise_comment: str
    improvement: str | None = None
    member_name: str
    member_phone: str
    consent: bool


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
