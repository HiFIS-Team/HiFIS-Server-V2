"""생일 축하 이모지 — 누가 누구에게 그날 보냈나 (2026-09-27 대표 요청).

생일 당일 앱을 열면 모달이 뜨고, 이모지를 누르면 생일자에게 푸시가 간다.
**한 사람이 한 생일에 한 번만** 보낸다 — 모달을 여러 번 열거나 연달아 눌러도
생일자 폰이 울리는 건 한 번이다. 해마다 다시 보낼 수 있게 `day` 로 가른다.
"""

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class BirthdayCheer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "birthday_cheers"
    __table_args__ = (UniqueConstraint("from_id", "to_id", "day", name="uq_birthday_cheer"),)

    from_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    to_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    #: 생일 당일 (KST)
    day: Mapped[date] = mapped_column(Date, nullable=False)
