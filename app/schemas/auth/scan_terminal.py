"""ScanTerminal DTO — 지점 출퇴근 단말."""

from datetime import datetime

from app.schemas.base import CamelModel


class ScanTerminalCreate(CamelModel):
    branch_id: str
    name: str


class ScanTerminalOut(CamelModel):
    id: str
    branch_id: str
    name: str
    issued_by_id: str
    revoked_at: datetime | None = None
    #: 마지막으로 스캔을 보낸 시각 — **단말이 살아 있는지 보는 유일한 단서다**
    last_used_at: datetime | None = None
    created_at: datetime


class ScanTerminalCreated(ScanTerminalOut):
    """발급 직후 한 번만 돌려주는 응답.

    **토큰 원문은 여기서만 볼 수 있다.** 서버는 해시만 들고 있어서 다시는
    보여줄 수 없다 — 잃어버리면 폐기하고 새로 발급한다.
    """

    token: str
