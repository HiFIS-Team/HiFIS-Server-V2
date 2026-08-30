"""Member DTO — CLAUDE.md §3.1."""

from datetime import datetime

from pydantic import Field

from app.enums import RegistrationType, VisitPath
from app.schemas.base import CamelModel
from app.schemas.members.registration import RegistrationOut


class MemberRegistrationInput(CamelModel):
    """회원 등록과 함께 발급할 첫 등록권(선택). 실무상 등록권 없는 회원은 없어 한 번에 받는다."""

    type: RegistrationType
    total_sessions: int = Field(gt=0)
    price_paid: int = Field(ge=0)
    session_unit_price: int = Field(ge=0)
    trainer_id: str | None = None  # 없으면 담당 트레이너(ownerTrainerId)
    #: 결제한 날 — 안 주면 지금. **기존 회원은 실제 결제일을 넣는다** (아래 설명)
    purchased_at: datetime | None = None
    #: 이미 받은 회차 — 앱을 켜기 전에 쓴 만큼. 안 주면 0 (옛 앱과 같다)
    used_sessions: int = Field(default=0, ge=0)


class MemberCreate(CamelModel):
    name: str
    phone: str
    branch_id: str
    owner_trainer_id: str
    referrer_member_id: str | None = None
    #: 어떻게 알고 왔나 — 블로그·인스타·OT→PT 면 담당 트레이너에게 5점.
    #:
    #: **선택으로 둔다.** 앱이 고르기 전에는 등록을 못 하게 막지만, 이미
    #: 배포된 옛 앱은 이 값을 안 보낸다 — 필수로 하면 그 앱에서 회원 등록이
    #: 통째로 막힌다. 안 오면 점수만 안 붙는다.
    visit_path: VisitPath | None = None
    memo: str | None = None
    registration: MemberRegistrationInput | None = None  # 있으면 회원+등록권을 한 트랜잭션으로


class MemberUpdate(CamelModel):
    name: str | None = None
    phone: str | None = None
    owner_trainer_id: str | None = None
    referrer_member_id: str | None = None
    #: 나중에 고칠 수 있다. **다만 점수는 등록할 때 한 번만 붙는다** —
    #: 여기서 바꿔도 이미 쌓인 점수는 그대로다 (되돌리면 지난달 랭킹이 흔들린다).
    visit_path: VisitPath | None = None
    memo: str | None = None
    #: 운동을 하는 이유 — 통기로 덮어쓴다(순서가 곧 번호다).
    #: 빈 줄은 서버가 걸러 낸다.
    goals: list[str] | None = Field(default=None, max_length=20)


class MemberOut(CamelModel):
    id: str
    name: str
    phone: str
    branch_id: str
    owner_trainer_id: str
    referrer_member_id: str | None = None
    visit_path: VisitPath | None = None
    registered_at: datetime
    memo: str | None = None
    goals: list[str] = Field(default_factory=list)
    #: 회원에게 보내는 주소의 마지막 칸 — `hifis.app/training/{token}`
    training_token: str | None = None


class MemberCreateOut(MemberOut):
    """POST /members 응답 — 등록권을 함께 발급했으면 실어 준다(추가 필드, 하위호환)."""

    registration: RegistrationOut | None = None
