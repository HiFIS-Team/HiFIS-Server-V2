"""PT 만족도 폼 DTO (2026-08-20)."""

from datetime import datetime

from pydantic import Field

from app.enums import RenewIntent
from app.schemas.base import CamelModel


class PtSurveyPageOut(CamelModel):
    """문자 링크를 열었을 때 화면이 받는 것 — **내줄 수 있는 것만** 담는다.

    로그인이 없는 자리라 회원의 연락처·등록권 금액 같은 건 안 나간다.
    이름은 넣는다 — "○○님" 이라고 부르지 않으면 남의 링크를 잘못 연 건지
    회원이 알 수 없다.
    """

    member_name: str
    trainer_name: str
    trainer_avatar_color: str
    branch_name: str
    session_no: int
    total_sessions: int
    #: 이미 냈나 — true 면 화면이 '이미 보내주셨어요' 로 떨어진다
    answered: bool


class PtSurveySubmit(CamelModel):
    satisfaction: int = Field(ge=1, le=5)
    #: 앞으로 트레이너에게 바라는 점 — **비워도 된다** (연장 여부만 답하고 끝낼 수 있다)
    request: str | None = None
    renew: RenewIntent


class PtSurveyOut(CamelModel):
    """대표·점장이 보는 한 줄 — 결과를 읽는 자리다."""

    id: str
    registration_id: str
    member_id: str
    member_name: str | None = None
    trainer_id: str
    trainer_name: str | None = None
    session_no: int
    #: 아직 문자를 못 보냈을 때 손으로 넘겨줄 수 있게 주소를 같이 준다.
    #: 모델에는 없는 값이라 `model_validate` 뒤에 라우터가 채운다 (그래서 기본값이 있다)
    url: str = ''
    sent_at: datetime | None = None
    answered_at: datetime | None = None
    satisfaction: int | None = None
    request: str | None = None
    renew: RenewIntent | None = None
    created_at: datetime
