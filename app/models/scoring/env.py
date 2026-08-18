"""환경정비 모델 — EnvItem · EnvTaskLog · SupplyOrder (CLAUDE.md §4.2)."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class EnvItem(UUIDMixin, TimestampMixin, Base):
    """지점별 환경정비 항목·배점 (예: 남탈/여탈 5, 복도 3, 빨래수거 1)."""

    __tablename__ = "env_items"

    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 표시 순서 — 배점순이 아니라 고정 순서(매일 쓰는 세탁이 아래로 안 가도록). 작을수록 위.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class EnvTaskLog(UUIDMixin, TimestampMixin, Base):
    """수행 기록 — 생성 시 item_name/points 스냅샷 (이후 항목 수정과 무관)."""

    __tablename__ = "env_task_logs"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    env_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("env_items.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 수행 사진과 위치 — **현수막만 필수다** (2026-08-18 대표 요청).
    #
    # 걸었다고 누르기만 하면 실제로 걸었는지 확인할 방법이 없어서, 사진과
    # 어디에 걸었는지를 같이 받는다. 나머지 항목은 지금처럼 그냥 눌러 남긴다.
    #
    # 컬럼 자체는 nullable 이다 — 이미 쌓인 기록에는 값이 없고, 어느 항목이
    # 필수인지는 라우터의 `PHOTO_REQUIRED_ITEMS` 가 정한다.
    photo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    place: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 프로젝트 할 일을 체크해서 저절로 생긴 기록이면 그 할 일 (2026-08-14)
    #
    # `현수막 설치 1` 처럼 할 일에 환경정비 항목 이름이 들어 있으면, 체크하는
    # 순간 이 기록이 같이 생긴다. **체크를 풀 때 정확히 걷으려고** 어디서 나온
    # 것인지 남긴다 — 없으면 그날 같은 항목 기록을 통째로 뒤져야 한다.
    #
    # 칩을 눌러 직접 남긴 기록은 null 이다.
    source_todo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_todos.id", ondelete="SET NULL"), nullable=True, index=True
    )


class SupplyOrder(UUIDMixin, TimestampMixin, Base):
    """비품 관리 — 월 누적·전달 대비 통계용."""

    __tablename__ = "supply_orders"

    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    ordered_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
