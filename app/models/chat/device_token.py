"""DeviceToken (앱 푸시 기기 토큰) 모델 — APNs 발송 대상.

`PushSubscription` 과 **따로 둔다.** 저쪽은 브라우저 웹푸시(VAPID)라
`endpoint · p256dh · auth` 를 들고 있는데, 앱 푸시는 **애플이 준 기기 토큰
한 줄**이 전부다. 한 테이블에 억지로 넣으면 절반이 늘 비어 있게 된다.

지금 DB 의 웹푸시 구독은 전부 예전 Safari(PWA) 흔적이라 앱과 상관이 없다
(backend-gap 78번).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class DeviceToken(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "device_tokens"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )

    #: APNs 기기 토큰(16진 문자열). **기기당 하나**라 유니크다.
    #:
    #: 같은 폰에 다른 사람이 로그인하면 **주인만 바뀐다** — 안 바꾸면
    #: 그 폰으로 앞사람 알림이 계속 간다.
    token: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)

    #: `IOS` · `MACOS` — 지금은 기록용이다 (보내는 주소는 아래 [sandbox] 가 정한다)
    platform: Mapped[str] = mapped_column(String(10), nullable=False, default="IOS")

    #: 개발용 토큰인가 — **빌드 모드가 정한다**, 기기 종류가 아니다.
    #:
    #: 디버그 빌드는 `api.sandbox.push.apple.com`, 릴리즈·TestFlight 는
    #: `api.push.apple.com` 이다. 틀린 쪽으로 보내면 `400 BadDeviceToken` 이라
    #: 앱이 등록할 때 같이 알려 준다.
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: 마지막으로 등록·갱신한 시각 — 안 쓰는 기기를 걸러내는 데 쓴다
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
