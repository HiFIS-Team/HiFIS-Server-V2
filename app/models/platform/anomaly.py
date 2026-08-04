"""이상행동 — 접속·활동 로그에서 찾아낸 수상한 흐름 (모니터링 '이상 징후').

로그는 '무슨 일이 있었나'를 낱개로 남긴다. 이 표는 그 낱개들을 **묶어서
판단한 결과**다 — 로그인 실패 한 번은 오타지만 10분에 다섯 번은 다른 뜻이다.

`app/workers/anomaly_scan.py` 가 5분마다 훑어 채운다. 찾을 때마다 새로 만들면
같은 사건이 스캔마다 쌓이므로 `window_key` 로 한 창에 한 줄만 남긴다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin
from app.enums import AnomalyKind


class Anomaly(UUIDMixin, Base):
    __tablename__ = "anomalies"

    kind: Mapped[AnomalyKind] = mapped_column(
        SAEnum(AnomalyKind, native_enum=False, length=20), nullable=False, index=True
    )

    # 누구 일인지 — 없는 계정으로 로그인을 시도하면 비어 있다
    employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 화면에 그대로 찍는 대상 — 이메일이거나 IP다 (계정이 없을 수 있어서)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)

    # 사람이 읽는 한 줄 — '10분 동안 로그인 5번 실패' 같은 것
    detail: Mapped[str] = mapped_column(String(300), nullable=False)

    # 몇 번이었나 — 심각도를 가르는 값
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # 같은 사건을 스캔마다 새로 만들지 않으려는 열쇠 (종류·대상·시간창)
    window_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    # 대표가 보고 '확인했다'고 누른 시각 — 안 눌렀으면 null
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
