"""KindnessSurvey (회원 친절도 설문) 모델 — CLAUDE.md §4.5.

외부 QR 폼(네이버폼 등)에서 웹훅으로 수신. 칭찬 직원에게 KINDNESS +10.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ComplaintStatus


class KindnessSurvey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "kindness_surveys"

    motivation: Mapped[str] = mapped_column(Text, nullable=False)  # ① 운동 시작 계기
    praised_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )  # ② 칭찬 직원
    praise_comment: Mapped[str] = mapped_column(Text, nullable=False)
    improvement: Mapped[str | None] = mapped_column(Text, nullable=True)  # ③ 보완점
    member_name: Mapped[str] = mapped_column(String(50), nullable=False)  # ④
    member_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False)  # ⑤ 동의(필수)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 컴플레인 처리 — `improvement` 가 적힌 설문에서만 의미가 있다.
    # 비어 있는 설문도 PENDING 으로 두지만 앱이 컴플레인으로 세지 않는다.
    improvement_status: Mapped[ComplaintStatus] = mapped_column(
        SAEnum(ComplaintStatus, native_enum=False, length=16),
        nullable=False,
        default=ComplaintStatus.PENDING,
        server_default=ComplaintStatus.PENDING.value,
    )
    #: 완료를 올린 사람 — 승인되면 **이 사람에게** 클레임해결 점수가 간다.
    #: 대표가 눌러 준다고 대표가 치운 것은 아니다.
    done_requested_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    done_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )

    #: 매장 TV 에 걸 **한 줄 요약** — 해결 완료로 넘어갈 때 한 번 만든다.
    #:
    #: TV 는 줄을 두 줄까지만 그리고 자르는데(`tv.css` 의 line-clamp), 길게 적은
    #: 의견이 `...` 로 끊겨서 넣었다 (2026-09-08 대표 요청).
    #:
    #: **비어 있으면 TV 가 원문(`improvement`)을 쓴다.** 요약을 못 만들었거나
    #: (키 없음·API 실패) 짧아서 안 줄인 것이라, 비어 있는 것이 정상 상태다.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: **매장 TV 에 안 건다** (2026-09-16 대표 결정)
    #:
    #: 해결은 해결인데 **벽에 걸 글이 아닌** 컴플레인이 있다. 사람이나 무리를
    #: 지목하는 것이 그렇다 — 실제로 두 건 나왔다.
    #:
    #: - `20-21시 운동부 학생들이 소란스럽다` (화순 09-15)
    #: - `빡빡머리 스타렉스 … 출입제한 했으면` (화순 08-30)
    #:
    #: 회원이 보는 벽에 다른 회원 이야기를 거는 셈이라 성격이 안 맞는다.
    #:
    #: **TV 에서만 뺀다.** 해결 완료·점수·문자·앱 기록은 그대로 간다 —
    #: 예전에는 `resolved_at` 을 비워서 뺐는데, 그건 '해결 시각이 없다' 라고
    #: 적는 것이라 뜻이 어긋났다.
    tv_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    #: 회원에게 해결 문자를 보낸 때 — **두 번 보내는 것을 막는다** (2026-09-08).
    #:
    #: 완료가 찍히는 자리가 둘이라(대표가 직접 · 대표가 승인) 안 막으면
    #: 같은 회원에게 문자가 두 통 간다. 요약(`summary`)과 같은 사정이다.
    sms_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
