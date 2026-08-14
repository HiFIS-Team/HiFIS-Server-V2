"""내 업무 모델 — MyTask · MyTaskCheck · MyTaskRequest (2026-08-14).

업무 화면 '환경정비' 자리가 **공통 업무 / 내 업무** 둘로 갈렸다.

| | 무엇 | 어떻게 도나 |
|---|---|---|
| 공통 업무 | 지점의 환경정비 항목 (`EnvItem`) | 하루에 **여러 번** — 할 때마다 횟수가 는다 |
| **내 업무** | 본인이 만드는 개인 목록 (`MyTask`) | 하루에 **한 번씩 체크** — 다 하면 완료, 남으면 누락 |

**점수를 안 붙인다 (2026-08-14 결정).** 공통 업무는 항목마다 배점이 있고
점수 원장에 쌓이는데, 내 업무는 그날 할 일을 챙기는 용도라 배점 칸이 없다.

**목록은 매일 같은 것이 반복된다.** 한 번 만들어 두면 매일 그 목록이 뜨고
체크만 초기화된다 (`MyTaskCheck` 가 날짜별로 따로 쌓인다).
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import MyTaskRequestType, ProjectRequestStatus


class MyTask(UUIDMixin, TimestampMixin, Base):
    """개인 업무 항목 — 매일 반복되는 내 할 일 하나."""

    __tablename__ = "my_tasks"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 표시 순서 — 작을수록 위. 환경정비 칩과 같은 규칙이다
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: 지운 항목 — **행을 지우지 않는다.**
    #:
    #: 지우면 그날 '다 했다/누락이다' 판정에 쓰인 체크 기록이 같이 사라져서,
    #: 지난 날짜를 다시 보면 하지도 않은 일을 한 것처럼 보인다.
    #: 목록에서만 빼고 기록은 남긴다.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MyTaskCheck(UUIDMixin, TimestampMixin, Base):
    """그날 그 업무를 했다는 표시 — 하루에 한 번뿐이다."""

    __tablename__ = "my_task_checks"
    __table_args__ = (
        # 같은 날 같은 업무를 두 번 체크할 수 없다 — 공통 업무와 다른 점이다
        UniqueConstraint("my_task_id", "date", name="uq_my_task_check_day"),
    )

    my_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("my_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 조회할 때 항목을 안 거치고 바로 거르려고 같이 둔다
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    #: **KST 근무일.** 근태 기록(`Attendance.date`)과 같은 기준이라
    #: '누락 상태로 퇴근했나'를 같은 날짜로 맞출 수 있다
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)


class MyTaskRequest(UUIDMixin, TimestampMixin, Base):
    """내 업무 수정·삭제 결재 — 본인이 올리고 **MASTER 가 승인·반려**한다.

    **추가는 결재가 없다.** 할 일을 늘리는 것은 스스로 하는 일이라 막을 이유가
    없지만, 고치고 지우는 것은 '안 한 일을 없던 일로 만드는' 길이 된다.
    프로젝트 수정·삭제와 같은 이유다 (backend-gap 68).

    **업무 하나에 대기 요청은 하나뿐이다.** 수정 대기 중에 삭제까지 올라오면
    어느 것을 먼저 처리하느냐로 결과가 갈린다.
    """

    __tablename__ = "my_task_requests"

    my_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("my_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[MyTaskRequestType] = mapped_column(
        SAEnum(MyTaskRequestType, native_enum=False, length=20), nullable=False
    )
    #: 고치겠다는 값 — EDIT 만 채운다. `{"content": "..."}`
    #:
    #: **승인하는 사람이 무엇을 승인하는지 보이려면 여기 있어야 한다.**
    #: 신청할 때 바로 항목에 쓰고 '되돌리기'를 두면 승인 전인데 이미 바뀐다.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProjectRequestStatus] = mapped_column(
        SAEnum(ProjectRequestStatus, native_enum=False, length=20),
        nullable=False,
        default=ProjectRequestStatus.PENDING,
    )
    requested_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
