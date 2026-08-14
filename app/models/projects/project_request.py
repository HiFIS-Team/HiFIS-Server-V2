"""ProjectRequest (프로젝트 결재 요청) 모델.

담당자·참여 멤버가 올리고 **MASTER 가 승인·반려**한다. 네 종류가 한 테이블을
쓴다 (`ProjectRequestType`).

| 종류 | 채우는 칸 | 승인하면 |
|---|---|---|
| EXTENSION·OVERDUE | `new_due` + `reason` | 기한이 바뀐다 |
| EDIT | `payload` + `reason` | 이름·설명·색이 바뀐다 |
| DELETE | `reason` | 프로젝트가 지워진다 |

**프로젝트당 대기 요청은 하나뿐이다.** 연장 대기 중에 삭제까지 올라오면
어느 것을 먼저 처리하느냐에 따라 결과가 달라진다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ProjectRequestStatus, ProjectRequestType


class ProjectRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_requests"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ProjectRequestType] = mapped_column(
        SAEnum(ProjectRequestType, native_enum=False, length=20), nullable=False
    )
    # 제안 새 기한 — EXTENSION·OVERDUE 만 채운다 (EDIT·DELETE 는 기한과 무관)
    new_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 고치겠다는 값 — EDIT 만 채운다. {"title": ..., "purpose": ..., "color": ...}
    #
    # **승인하는 사람이 무엇을 승인하는지 보이려면 여기 있어야 한다.** 신청할 때
    # 바로 프로젝트에 쓰고 '되돌리기'를 두면, 승인 전인데 이미 바뀐 이름이 뜬다.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # 신청 사유 (종류 불문 필수)
    status: Mapped[ProjectRequestStatus] = mapped_column(
        SAEnum(ProjectRequestStatus, native_enum=False, length=20),
        nullable=False,
        default=ProjectRequestStatus.PENDING,
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id"), nullable=False, index=True
    )
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 반려 사유(필수)
