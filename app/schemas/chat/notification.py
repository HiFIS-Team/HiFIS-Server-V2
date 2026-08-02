"""알림·웹푸시 DTO — CLAUDE.md §6.10."""

from datetime import datetime

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
