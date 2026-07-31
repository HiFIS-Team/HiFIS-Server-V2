"""접속 로그 — 로그인 이벤트 감사 (개인정보처리방침 §1-1·§3·§8).

접속 일시·IP·User-Agent·이벤트(성공/실패)를 기록한다.
보존기간(access_log_retention_days, 기본 90일)이 지나면 retention 잡이 파기(통신비밀보호법, §3).
로그인 실패는 계정이 없을 수 있으므로 employee_id 없이 email(시도한 식별자)만 남을 수 있다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin
from app.enums import AccessEvent


class AccessLog(UUIDMixin, Base):
    __tablename__ = "access_logs"

    # 직원 소프트삭제(탈퇴)여도 유지 → 하드삭제 시엔 NULL 로 이력 보존
    employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 시도한 로그인 식별자(실패 추적용)
    event: Mapped[AccessEvent] = mapped_column(
        SAEnum(AccessEvent, native_enum=False, length=20), nullable=False
    )
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)          # IPv6 최대 45자
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # 파기(범위 삭제)·정렬 조회 모두 created_at 기준 → 인덱스
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
