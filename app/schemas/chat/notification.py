"""알림·웹푸시 DTO — CLAUDE.md §6.10."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class NotificationOut(CamelModel):
    id: str
    employee_id: str
    type: str
    title: str
    body: str | None = None
    link: str | None = None
    read: bool
    created_at: datetime


class PushKeys(CamelModel):
    p256dh: str
    auth: str


class PushSubscribeIn(CamelModel):
    endpoint: str
    keys: PushKeys


class VapidPublicKeyOut(CamelModel):
    public_key: str  # 프론트 구독 생성용 applicationServerKey


class DeviceTokenIn(CamelModel):
    """앱이 애플에게 받은 기기 토큰 — `POST /push/devices`

    [sandbox] 는 **빌드 모드**다. 디버그 빌드로 받은 토큰은 개발용 주소로만
    닿아서, 앱이 `kDebugMode` 를 그대로 실어 보낸다. 틀리면 `BadDeviceToken` 이다.
    """

    token: str = Field(min_length=32, max_length=200)
    platform: str = "IOS"  # IOS | MACOS
    sandbox: bool = False
