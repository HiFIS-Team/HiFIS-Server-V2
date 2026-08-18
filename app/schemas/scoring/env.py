"""환경정비 DTO — CLAUDE.md §4.2."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class EnvItemCreate(CamelModel):
    branch_id: str
    name: str
    points: int = Field(gt=0)
    editable: bool = True
    sort_order: int = 1000  # 신규 커스텀 항목은 기본 목록(0~) 아래로


class EnvItemUpdate(CamelModel):
    name: str | None = None
    points: int | None = Field(default=None, gt=0)
    editable: bool | None = None
    sort_order: int | None = None  # 재정렬


class EnvItemOut(CamelModel):
    id: str
    branch_id: str
    name: str
    points: int
    editable: bool
    sort_order: int


class EnvLogCreate(CamelModel):
    env_item_id: str
    note: str | None = Field(default=None, max_length=80)  # 기타 등 write-in 텍스트 → 라벨 "기타(내용)"
    # 현수막처럼 확인이 필요한 항목만 채워 보낸다 (`POST /env-logs/photo` 가 돌려준 주소).
    # 나머지 항목은 안 보내면 그만이다.
    photo_url: str | None = Field(default=None, max_length=255)
    place: str | None = Field(default=None, max_length=100)


class EnvLogPhotoOut(CamelModel):
    """올린 사진의 서빙 주소 — 이걸 [EnvLogCreate.photo_url] 에 실어 보낸다."""

    url: str


class EnvTaskLogOut(CamelModel):
    id: str
    employee_id: str
    branch_id: str
    env_item_id: str
    item_name: str
    points: int
    note: str | None = None
    photo_url: str | None = None
    place: str | None = None
    created_at: datetime


class SupplyOrderCreate(CamelModel):
    branch_id: str
    item_name: str
    price: int = Field(ge=0)


class SupplyOrderOut(CamelModel):
    id: str
    branch_id: str
    item_name: str
    price: int
    ordered_by_id: str
    created_at: datetime
