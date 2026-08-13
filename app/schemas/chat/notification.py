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
    """앱이 받은 기기 토큰 — `POST /push/devices`

    [platform] 이 **어느 길로 보낼지를 정한다** — 애플은 APNs 로 직접 치고
    안드로이드는 FCM 을 거친다 (구글이 다른 길을 안 준다).

    [sandbox] 는 **빌드 모드**이고 애플에만 뜻이 있다. 디버그 빌드로 받은
    토큰은 개발용 주소로만 닿아서, 앱이 `kDebugMode` 를 그대로 실어 보낸다.
    틀리면 `BadDeviceToken` 이다. FCM 에는 이 구분이 없어서 안드로이드는 늘 false 다.
    """

    token: str = Field(min_length=32, max_length=200)
    platform: str = "IOS"  # IOS | MACOS | ANDROID
    sandbox: bool = False
