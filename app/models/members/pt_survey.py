"""PT 만족도 폼 — 회원이 **7회차마다** 문자로 받는 설문 (2026-08-20 · 09-27).

매장 QR 설문(`KindnessSurvey`)과 **다른 것이다.**

| | 누구에게 | 언제 | 무엇을 |
|---|---|---|---|
| 매장 QR 설문 | 아무 회원이나 | 아무 때나 | 직원 칭찬 · 개선 의견 |
| **PT 만족도 폼** | **그 회원 한 명** | **누적 7·14·21…회차** | 만족도 · 바라는 점 · 연장 여부 |

**회원 누적 회차로 센다** — 운동일지 번호와 같은 수라 재등록해도 이어진다.
회원·회차당 한 줄이다. 첫 번째(7회차)와 그 뒤는 문자 말이 다르다
(`session_signs._SMS_TEMPLATE_AGAIN`). 2026-09-27 전에는 신규 등록권의
7회차 한 번뿐이었다.

**토큰이 곧 열쇠다.** 문자로 보내는 주소라 로그인이 없다. 회원 이름·연락처를
주소에 안 담고, 화면에도 **이름과 트레이너만** 내보낸다.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import RenewIntent


class PtSurvey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "pt_surveys"

    #: 그 회차를 찍은 등록권 — 7회차마다 열어서 **한 등록권에 여럿일 수 있다**
    #: (2026-09-27 전에는 등록권당 하나라 유니크였다)
    registration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("registrations.id"), nullable=False, index=True
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
    #: 몇 회차에 보냈나 — **회원 누적 회차**(7·14·21…). 회원·회차당 하나다
    session_no: Mapped[int] = mapped_column(Integer, nullable=False)

    #: 문자를 **실제로** 보낸 시각 — 발신번호가 정해지기 전에는 비어 있다
    #: (줄은 만들어 두고 링크만 들고 있는 상태다)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 회원이 답한 시각 — 비어 있으면 아직 안 냈다
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: 만족도 1~5
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 앞으로 트레이너에게 바라는 점 — **옛 설문의 서술형 한 칸이다.**
    #:
    #: 2026-09-16 에 객관식(`praise`·`improve`)으로 갈아탔다. 새 답은 여기를
    #: 안 채우지만 **지우지 않는다** — 그 전에 받은 답이 22건 있고, 그것만
    #: 담긴 칸이라 지우면 통째로 사라진다.
    request: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: 좋았던 점 — `[{"topic": "DIET", "note": "사진 보내면 바로 답을 주셔요"}]`
    #:
    #: **주제(`topic`)는 `app/services/pt_topics.py` 의 코드다.** 문구를 안 담는
    #: 이유는 거기 적어 두었다 (문구를 고치면 이미 낸 답까지 같이 바뀌어야 한다).
    #: `note` 는 **비어 있을 수 있다** — 주제만 고르고 넘어가도 된다.
    praise: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: 보완할 점 — 모양은 `praise` 와 같고 **문구만 요청형**이다
    improve: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: 연장 여부
    renew: Mapped[RenewIntent | None] = mapped_column(
        SAEnum(RenewIntent, native_enum=False, length=20), nullable=True
    )
