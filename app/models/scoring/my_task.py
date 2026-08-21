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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import MyTaskRequestType, ProjectRequestStatus


class MyTask(UUIDMixin, TimestampMixin, Base):
    """개인 업무 항목 — 정한 요일마다 돌아오는 내 할 일 하나."""

    __tablename__ = "my_tasks"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 돌아오는 요일 — **ISO 1(월)~7(일)** (`Employee.work_days` 와 같은 규칙)
    #:
    #: **요일이 없으면 매일이 아니라 누락이 된다 (2026-08-20 요청).** 예전에는
    #: 목록이 매일 통째로 떠서, 금요일에만 하는 대청소를 넣으면 월~목에도 서고
    #: 안 누른 그 나흘이 전부 누락이었다.
    #:
    #: 같은 업무가 여러 요일에 걸릴 수 있다 (세탁 = 매일, 대청소 = 금).
    #: 기존 항목은 마이그레이션에서 **전부 매일**로 채웠다 — 그때는 매일이
    #: 전제였으므로 그게 그 사람들이 정한 값이다.
    weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{1,2,3,4,5,6,7}"
    )
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


class MyTaskMiss(UUIDMixin, TimestampMixin, Base):
    """**확정 누락** — 다음 근무일까지도 안 한 하루 (2026-08-21 대표 결정).

    퇴근할 때 오는 빨간 알림은 아직 누락이 아니다. 그날 못 한 일은 다음
    근무일로 밀려 와서(`services/my_tasks.py`) 한 번 더 기회가 있고,
    **그 날까지도 안 하면** 그때 이 행이 생긴다.

    ```
    금  대청소 ○ 안 함        빨간 알림 (아직 확정 아님)
    토·일 (쉬는 날)           안 센다 — 손쓸 방법이 없는 날이다
    월  밀린 일: 대청소 ○     여기서 체크하면 회복
        안 하면                → 화요일 잡이 **금요일**을 확정 누락으로 남긴다
    ```

    ## 하루에 한 줄이다

    같은 날 업무를 세 개 빠뜨려도 한 줄이다 (`uq_my_task_miss_day`).
    당사자 감점이 **-20점 고정**이고 점장 기본급 차감도 **하루 단위**라
    그렇게 정했다 (2026-08-21). 몇 개였는지는 [task_count] 에 남는다.

    ## 사유서로 되돌린다

    확정되면 점수가 먼저 깎이고, 사유서를 내서 **승인받으면 회복**된다
    (`excuse_status == APPROVED`). 회복하면 깎았던 점수 줄을 지운다 —
    되돌린다는 말이 그 뜻이다.
    """

    __tablename__ = "my_task_misses"
    __table_args__ = (
        # 하루에 한 줄 — 잡이 여러 번 돌아도, 업무를 몇 개 빠뜨렸어도 하나다
        UniqueConstraint("employee_id", "date", name="uq_my_task_miss_day"),
    )

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    #: 점장 차감이 지점으로 센다 — 셀 때마다 직원 행을 다시 읽지 않으려고 같이 둔다
    branch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=True, index=True
    )
    #: **누락한 날** — 밀려 온 날이 아니라 원래 차례였던 날 (KST 근무일)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: 그날 몇 개를 빠뜨렸나 — 표시용. 판정에는 안 쓴다
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 무엇을 빠뜨렸나 — `["대청소", "세탁"]`. 업무를 나중에 고쳐도 그때 것이 남는다
    contents: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #: 깎은 점수 줄 — 회복할 때 이 줄을 지운다. 이미 지웠으면 `None`
    score_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    #: 사유서 — `None` 이면 아직 안 냈다
    excuse_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `None` 안 냄 · PENDING 대기 · APPROVED **회복** · REJECTED 확정
    excuse_status: Mapped[ProjectRequestStatus | None] = mapped_column(
        SAEnum(ProjectRequestStatus, native_enum=False, length=20), nullable=True
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def excused(self) -> bool:
        """사유가 승인돼 없던 일이 됐나 — 점수·점장 차감에서 다 빠진다."""
        return self.excuse_status == ProjectRequestStatus.APPROVED


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
