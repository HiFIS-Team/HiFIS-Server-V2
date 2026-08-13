"""SSH 로 들어온 적 있는 IP — 알림을 **처음 보는 곳에서만** 내려고 기억한다.

2026-08-11 침해 사고 뒤에 SSH 접속 알림을 붙였는데, 세션이 열릴 때마다 한 건씩
가서 개발자가 서버를 만지는 동안 알림이 쏟아졌다 (한 번 살펴보는 데 열 건).
그래서 **아는 IP 는 조용히** 지나가고 낯선 곳에서 들어올 때만 알린다
(2026-08-13 결정).

지역도 여기 캐시한다 — 같은 IP 를 두 번 조회할 이유가 없다.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class SshHost(Base, UUIDMixin):
    __tablename__ = "ssh_hosts"

    ip: Mapped[str] = mapped_column(String(45), unique=True, index=True, nullable=False)

    # 마지막으로 이 IP 에서 들어온 때 — 여기서 오래 지나면 다시 '처음 보는 곳'이다
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 조회해 둔 지역 ("대한민국 광주" · "내부망"). 못 알아내면 null
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
