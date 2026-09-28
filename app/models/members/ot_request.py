"""OT 신청 — 네이버 플레이스·전단지 QR 로 들어온 사람이 **로그인 없이** 낸다 (2026-09-28).

| 단계 | 누가 | 무엇 |
|---|---|---|
| 신청 | 손님 | 이름·성별·나이·연락처·운동 목적·방문 날짜와 시간, 개인정보 동의 |
| 배정 | MASTER·ADMIN·MANAGER | 상담할 사람을 고른다 |
| 수락 | 배정받은 사람 | 시간을 고칠 수 있다. 거절하면 다시 미배정 |
| 확정 | — | 공통 일정에 `000님 OT` · 신청자에게 문자 |
| 전환 | — | 이름·연락처가 같은 **신규 등록**이 들어오면 담당자에게 매출성과 +10 |

신청한 지점은 주소의 토큰으로 정한다 — 회원 설문과 같은 `branches.survey_token` 이다.
"""

from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import Gender, OtStatus


class OtRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ot_requests"

    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    gender: Mapped[Gender] = mapped_column(SAEnum(Gender, native_enum=False, length=10), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 숫자만 (`normalize_phone`) — 신규 등록과 짝지을 때 이 값으로 맞춘다
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    #: 운동 목적 — 회원 설문과 같은 보기에서 고른 글자 그대로
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)

    #: 방문 날짜와 시간 (KST) — 담당자가 수락하면서 고칠 수 있다
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    #: 개인정보 수집 동의 시각
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[OtStatus] = mapped_column(
        SAEnum(OtStatus, native_enum=False, length=20),
        nullable=False,
        default=OtStatus.PENDING,
        index=True,
    )
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True, index=True
    )
    assigned_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 확정하면서 만든 공통 일정
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    sms_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: PT 로 전환된 시각 — 이름·연락처가 같은 신규 등록이 들어왔다 (+10 은 한 번만)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
