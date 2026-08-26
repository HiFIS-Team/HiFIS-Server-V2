"""ScanTerminal DTO — 지점 출퇴근 단말."""

from datetime import datetime

from app.schemas.base import CamelModel


class ScanTerminalCreate(CamelModel):
    branch_id: str
    name: str


class ScanTerminalHeartbeat(CamelModel):
    """단말이 5분마다 보내는 생존 신호.

    [scanner_port] 는 **지금 붙잡고 있는 포트**다. 못 찾는 중이면 null 을
    보낸다 — 그래야 '프로그램은 도는데 스캐너를 못 잡았다'를 가릴 수 있다.
    """

    scanner_port: str | None = None


class ScanTerminalOut(CamelModel):
    id: str
    branch_id: str
    name: str
    issued_by_id: str
    revoked_at: datetime | None = None
    #: 마지막으로 **사람이 찍은** 시각. 생존 신호는 여기를 안 민다 —
    #: 같이 밀면 아무도 안 찍은 날에도 방금 찍은 것처럼 보인다
    last_used_at: datetime | None = None

    #: 생존 신호 (2026-08-26). 전부 null 이면 옛 스크립트가 도는 단말이라
    #: **살았는지 죽었는지를 알 수 없다** — '꺼져 있다'와 다르다
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    scanner_at: datetime | None = None
    #: null 인데 하트비트가 살아 있으면 **스캐너를 못 찾는 중**이다
    scanner_port: str | None = None

    created_at: datetime


class ScanTerminalCreated(ScanTerminalOut):
    """발급 직후 한 번만 돌려주는 응답.

    **토큰 원문은 여기서만 볼 수 있다.** 서버는 해시만 들고 있어서 다시는
    보여줄 수 없다 — 잃어버리면 폐기하고 새로 발급한다.
    """

    token: str
