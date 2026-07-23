"""WebSocket 연결 매니저 — 인메모리 팬아웃 (CLAUDE.md §9.3).

홈서버 단일 프로세스 전제. 다중 워커로 확장 시 Redis pub/sub 로 교체.
employee_id → 활성 소켓 집합(멀티 탭/기기 지원). 방 브로드캐스트는
서비스가 방 멤버 id 목록을 넘겨 send_to 로 보낸다.
"""

from starlette.websockets import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._active: dict[str, set[WebSocket]] = {}

    async def connect(self, employee_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._active.setdefault(employee_id, set()).add(ws)

    def disconnect(self, employee_id: str, ws: WebSocket) -> None:
        conns = self._active.get(employee_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._active.pop(employee_id, None)

    def is_online(self, employee_id: str) -> bool:
        return bool(self._active.get(employee_id))

    async def send_to(self, employee_ids: list[str], payload: dict) -> None:
        """대상 직원들의 모든 활성 소켓으로 전송. 죽은 소켓은 정리."""
        for eid in employee_ids:
            for ws in list(self._active.get(eid, ())):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.disconnect(eid, ws)


manager = ConnectionManager()
