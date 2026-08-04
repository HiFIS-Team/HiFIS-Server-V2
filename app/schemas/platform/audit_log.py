"""활동 로그 조회 DTO — 관리자 이상 (개인정보처리방침 §8)."""

from datetime import datetime

from pydantic import computed_field

from app.schemas.base import CamelModel
from app.services.audit import label


class AuditLogOut(CamelModel):
    id: str
    employee_id: str | None = None
    method: str
    path: str
    route: str
    status: int
    payload: dict | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @computed_field
    @property
    def action(self) -> str:
        """`공지 작성` 같은 사람 말 — 라벨표에 없으면 `POST /foo` 로 떨어진다"""
        return label(self.method, self.route)

    @computed_field
    @property
    def ok(self) -> bool:
        """실패한 시도(403·400·401)를 앱이 따로 세도록"""
        return 200 <= self.status < 300
