"""PT 만족도 폼 DTO (2026-08-20)."""

from datetime import datetime

from pydantic import Field, field_validator

from app.enums import RenewIntent
from app.schemas.base import CamelModel
from app.services import pt_topics


class PtTopicOut(CamelModel):
    """화면이 그릴 객관식 항목 하나 — **문구는 서버가 정한다.**

    웹폼도 앱도 이 값을 그리므로, 문구를 고치면 앱을 다시 안 올려도 바뀐다
    (`app/services/pt_topics.py` 참고).
    """

    code: str
    #: 좋았던 점 화면에 뜨는 말 (칭찬형)
    praise: str
    #: 보완할 점 화면에 뜨는 말 (요청형)
    improve: str


class PtTopicAnswer(CamelModel):
    """고른 주제 하나 — 낼 때도 읽을 때도 이 모양이다."""

    topic: str
    #: 그 주제에 적은 상세 — **비어 있을 수 있다** (고르기만 해도 된다)
    note: str | None = None
    #: 읽을 때만 채운다 — 저장에는 코드만 남고 문구는 표에서 붙인다
    label: str | None = None

    @field_validator("note")
    @classmethod
    def _trim(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v[: pt_topics.MAX_NOTE] if v else None


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
    #: 객관식 항목표 — **화면이 이걸 그대로 그린다**
    topics: list[PtTopicOut] = []


class PtSurveySubmit(CamelModel):
    satisfaction: int = Field(ge=1, le=5)
    #: 좋았던 점 · 보완할 점 — **둘 다 하나 이상 골라야 한다** (2026-09-16 결정).
    #: 글은 안 적어도 된다 — 주제만 남아도 셀 수 있다.
    praise: list[PtTopicAnswer] = []
    improve: list[PtTopicAnswer] = []
    #: 옛 서술형 칸 — **지금 웹폼은 안 보낸다.**
    #: 받는 것만 남겨 둔다. 객관식으로 갈아타기 전에 열어 둔 링크를 그대로 들고
    #: 있던 사람이 내면 여기로 오는데, 422 로 튕기면 로그인이 없는 자리라
    #: 다시 써 달라고 할 방법이 없다
    request: str | None = None
    renew: RenewIntent

    @field_validator("praise", "improve")
    @classmethod
    def _clean(cls, v: list[PtTopicAnswer]) -> list[PtTopicAnswer]:
        """모르는 주제를 버리고 같은 주제를 한 번만 남긴다.

        **여기서 422 를 내지 않는다** — 표에서 주제를 지운 뒤 열려 있던 화면이
        내는 경우가 있고, 그때 회원의 답 전체를 물리면 손해가 더 크다.
        """
        seen: set[str] = set()
        out: list[PtTopicAnswer] = []
        for item in v:
            if not pt_topics.is_known(item.topic) or item.topic in seen:
                continue
            seen.add(item.topic)
            out.append(item)
        return out[: len(pt_topics.PT_TOPICS)]


class PtSurveyOut(CamelModel):
    """대표·점장이 보는 한 줄 — 결과를 읽는 자리다."""

    id: str
    registration_id: str
    member_id: str
    member_name: str | None = None
    trainer_id: str
    trainer_name: str | None = None
    #: 그 등록권의 결제액(원) — '연장할래요' 로 답한 건을 다음달 예상 매출로
    #: 합산할 때 쓴다. 모델에는 없는 값이라 라우터가 등록권을 조인해 채운다
    price_paid: int | None = None
    #: 회원 소속 지점 — 지점별 예상 매출을 가르는 자리라 라우터가 채운다
    branch_name: str | None = None
    session_no: int
    #: 아직 문자를 못 보냈을 때 손으로 넘겨줄 수 있게 주소를 같이 준다.
    #: 모델에는 없는 값이라 `model_validate` 뒤에 라우터가 채운다 (그래서 기본값이 있다)
    url: str = ''
    sent_at: datetime | None = None
    answered_at: datetime | None = None
    satisfaction: int | None = None
    #: 옛 설문의 서술형 답 — 2026-09-16 이전 것에만 들어 있다
    request: str | None = None
    #: 고른 주제들 — `label` 이 채워져 오므로 앱이 문구표를 따로 안 든다
    praise: list[PtTopicAnswer] = []
    improve: list[PtTopicAnswer] = []
    renew: RenewIntent | None = None
    created_at: datetime
