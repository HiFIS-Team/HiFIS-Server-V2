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
    #: 매장 TV 에 걸지 — **대표가 직접 완료로 찍을 때만 쓴다** (2026-09-16).
    #: 끄면 벽에서만 빠지고 해결·점수·문자·앱 기록은 그대로 간다.
    #: 안 주면 예전처럼 걸린다.
    on_wall: bool = True


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
    #: 완료를 올린 사람 — 승인되면 이 사람에게 클레임해결 점수가 간다
    done_requested_by_id: str | None = None
    done_requested_at: datetime | None = None
    resolved_at: datetime | None = None
    #: **매장 TV 에 안 걸린 것** — 승인할 때 대표가 고른다
    tv_hidden: bool = False
    resolved_by_id: str | None = None
