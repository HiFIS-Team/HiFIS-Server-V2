"""Supplement DTO — 영양제 권유 한 줄.

칸 이름은 트레이너가 쓰던 표 그대로다 — `영양제 / 얼마나? / 언제? / 왜? / 기억하기`.
이름 말고는 다 비워 둘 수 있다. 상담 자리에서 이름만 먼저 적어 두고 나중에
채우는 일이 잦아서, 필수로 묶으면 적다 말고 못 저장한다.
"""

from pydantic import Field

from app.schemas.base import CamelModel

#: 회원 한 사람에게 담을 수 있는 줄 수 — 사람이 손으로 적는 값이라 이 위는 사고다
MAX_SUPPLEMENTS = 40


class SupplementCreate(CamelModel):
    member_id: str
    name: str = Field(min_length=1, max_length=60)
    dose: str = Field(default="", max_length=80)
    timing: str = Field(default="", max_length=80)
    reason: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=500)


class SupplementUpdate(CamelModel):
    """고칠 칸만 보낸다 — 안 보낸 칸은 그대로 둔다."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    dose: str | None = Field(default=None, max_length=80)
    timing: str | None = Field(default=None, max_length=80)
    reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class SupplementOut(CamelModel):
    id: str
    member_id: str
    name: str
    dose: str
    timing: str
    reason: str
    note: str
    sort_order: int
    author_id: str | None = None
