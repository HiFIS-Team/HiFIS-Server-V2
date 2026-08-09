"""InviteKey (초대키) 모델 — CLAUDE.md §2.3."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import EmploymentType, InviteStatus, Rank, Role


class InviteKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "invite_keys"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.id"), nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role, native_enum=False, length=20), nullable=False)
    rank: Mapped[Rank] = mapped_column(SAEnum(Rank, native_enum=False, length=20), nullable=False)

    #: 고용 형태 — 이 키로 가입하면 그대로 붙는다 (§2.6 알바).
    #:
    #: **알바를 뽑는 유일한 길이다.** 이게 없을 때는 어느 키로 가입하든
    #: `Employee.employment_type` 기본값(정규직)으로 들어와서, 알바로 들어온
    #: 사람을 대표가 나중에 손으로 바꿔 줘야 했다.
    #: 들어온 뒤 정규직으로 올리거나 퇴사시키는 건 `PATCH /employees/{id}`
    #: (MASTER) 쪽이다 — 여기는 **처음 들어올 때**만 정한다.
    employment_type: Mapped[EmploymentType] = mapped_column(
        SAEnum(EmploymentType, native_enum=False, length=20),
        nullable=False,
        default=EmploymentType.FULL_TIME,
        server_default=EmploymentType.FULL_TIME.value,
    )

    team: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[InviteStatus] = mapped_column(
        SAEnum(InviteStatus, native_enum=False, length=20),
        nullable=False,
        default=InviteStatus.UNUSED,
    )
    issued_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
