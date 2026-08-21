"""PT 만족도 폼 — 신규 회원이 **7회차를 마쳤을 때** 문자로 보내는 설문 (2026-08-20).

매장 QR 설문(`KindnessSurvey`)과 **다른 것이다.**

| | 누구에게 | 언제 | 무엇을 |
|---|---|---|---|
| 매장 QR 설문 | 아무 회원이나 | 아무 때나 | 직원 칭찬 · 개선 의견 |
| **PT 만족도 폼** | **그 등록권의 회원 한 명** | **신규 7회차** | 만족도 · 바라는 점 · 연장 여부 |

**등록권 하나에 한 번뿐이다.** 회차를 세다 7에 닿으면 만들고, 재등록하면
그 등록권에서 다시 7회차에 만든다 (등록권이 다르니 다른 줄이다).

**토큰이 곧 열쇠다.** 문자로 보내는 주소라 로그인이 없다. 회원 이름·연락처를
주소에 안 담고, 화면에도 **이름과 트레이너만** 내보낸다.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import RenewIntent


class PtSurvey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "pt_surveys"

    #: 어느 등록권의 7회차인가 — **등록권당 하나**라 유니크다
    registration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("registrations.id"), nullable=False, unique=True, index=True
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=False, index=True
    )
    #: **7회차를 수행한 트레이너.** 등록권의 담당이 아니라 그날 실제로 수업한 사람이다 —
    #: 대타로 들어간 사람에게 "바라는 점"을 물으면 어긋난다
    trainer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    #: 문자로 보내는 주소의 마지막 칸 — `/pt/{token}`
    token: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    #: 몇 회차에 보냈나 — 지금은 늘 7이지만 기준이 바뀌면 옛 줄이 뜻을 잃지 않게 남긴다
    session_no: Mapped[int] = mapped_column(Integer, nullable=False)

    #: 문자를 **실제로** 보낸 시각 — 발신번호가 정해지기 전에는 비어 있다
    #: (줄은 만들어 두고 링크만 들고 있는 상태다)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 회원이 답한 시각 — 비어 있으면 아직 안 냈다
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: 만족도 1~5
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 앞으로 트레이너에게 바라는 점 — **서술형이다.**
    #: 점수로 받으면 무엇을 바라는지가 안 남는다 (바꿀 거리가 안 나온다)
    request: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 연장 여부
    renew: Mapped[RenewIntent | None] = mapped_column(
        SAEnum(RenewIntent, native_enum=False, length=20), nullable=True
    )
