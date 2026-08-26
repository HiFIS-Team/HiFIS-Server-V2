"""WebSocket 연결 매니저 — Redis pub/sub 팬아웃 (CLAUDE.md §9.3).

각 워커 프로세스는 자신에게 붙은 소켓만 메모리로 안다(`_active`).
방 브로드캐스트(`send_to`)는 **Redis 채널로 발행** → 모든 워커가 그 채널을 구독해
자기 로컬 소켓에 배달한다. 이렇게 gunicorn 워커가 몇 개든 실시간이 유지된다
(발행 워커도 자기 발행을 되받아 자기 소켓에 배달 → 정확히 1회씩).

Redis 미설정/연결 실패 시엔 **로컬 직접 배달로 폴백**(단일 프로세스 개발용) —
앱은 그대로 뜨고 채팅도 동작한다(단, 워커 1개 전제).
"""

import asyncio
import json
import logging

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

_CHANNEL = "hifis:ws:chat"

#: 한 사람이 동시에 열 수 있는 소켓 수 — 폰·PC·태블릿을 같이 써도 남는 값이다.
#: 상한이 없으면 유효 토큰 한 장으로 수천 개를 열어 워커 메모리를 채울 수 있다.
_MAX_SOCKETS_PER_EMPLOYEE = 8

#: 구독이 끊겼을 때 다시 붙기까지 — 실패할수록 늘린다
_RESUBSCRIBE_MIN_S = 1
_RESUBSCRIBE_MAX_S = 30


class ConnectionManager:
    def __init__(self) -> None:
        self._active: dict[str, set[WebSocket]] = {}
        self._redis = None  # redis.asyncio.Redis | None (설정·연결되면 세팅)
        self._pubsub = None
        self._reader_task: asyncio.Task | None = None

    # ── 로컬 소켓 관리(이 워커 내부) ──
    async def connect(self, employee_id: str, ws: WebSocket) -> None:
        await ws.accept()
        conns = self._active.setdefault(employee_id, set())
        # 넘치면 기존 것부터 닫는다 — 새 연결을 거절하면 방금 앱을 켠 사람이
        # 못 붙는다(끊긴 소켓이 아직 정리 안 됐을 때가 흔하다)
        while len(conns) >= _MAX_SOCKETS_PER_EMPLOYEE:
            victim = next(iter(conns))
            conns.discard(victim)
            try:
                await victim.close(code=1008)
            except Exception:
                pass
        conns.add(ws)

    def disconnect(self, employee_id: str, ws: WebSocket) -> None:
        conns = self._active.get(employee_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._active.pop(employee_id, None)

    def is_online(self, employee_id: str) -> bool:
        """이 워커 기준 접속 여부(교차 워커 아님 — 현재 서비스는 미사용)."""
        return bool(self._active.get(employee_id))

    async def _local_send(self, employee_ids: list[str], payload: dict) -> None:
        """이 워커의 로컬 소켓에만 배달. 죽은 소켓은 정리."""
        for eid in employee_ids:
            for ws in list(self._active.get(eid, ())):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.disconnect(eid, ws)

    async def _local_kick(self, employee_ids: list[str]) -> None:
        """이 워커의 로컬 소켓을 끊는다 — 세션이 폐기된 사람."""
        for eid in employee_ids:
            for ws in list(self._active.get(eid, ())):
                self.disconnect(eid, ws)
                try:
                    await ws.close(code=4401)  # 앱이 '인증 실패'로 읽는 코드
                except Exception:
                    pass

    # ── 팬아웃(교차 워커) ──
    async def send_to(self, employee_ids: list[str], payload: dict) -> None:
        """대상 직원들에게 전송.

        Redis 연결 시: 채널로 발행만 하고 리턴 → 모든 워커의 리더가 자기 로컬 소켓에 배달.
        Redis 미연결 시: 이 프로세스 로컬 소켓에 직접 배달(폴백).
        """
        if self._redis is not None:
            try:
                await self._redis.publish(
                    _CHANNEL, json.dumps({"employeeIds": employee_ids, "payload": payload})
                )
                return
            except Exception:
                logger.warning("ws Redis publish 실패 → 로컬 폴백", exc_info=True)
        await self._local_send(employee_ids, payload)

    async def kick(self, employee_ids: list[str]) -> None:
        """이 사람들의 소켓을 **모든 워커에서** 끊는다.

        로그아웃·비번 재설정·정지·퇴사처럼 세션을 폐기하는 자리가 부른다.
        접속 시점에만 검사하면 이미 붙어 있는 소켓은 토큰 만료(30분)까지 살아남는다.
        """
        if self._redis is not None:
            try:
                await self._redis.publish(
                    _CHANNEL, json.dumps({"employeeIds": employee_ids, "kick": True})
                )
                return
            except Exception:
                logger.warning("ws Redis kick 발행 실패 → 로컬 폴백", exc_info=True)
        await self._local_kick(employee_ids)

    # ── 생명주기(앱 lifespan에서 호출) ──
    async def start(self, redis_url: str | None) -> None:
        """Redis 구독 시작. 실패해도 앱은 계속(로컬 모드로 폴백)."""
        if not redis_url:
            logger.info("ws: REDIS_URL 없음 → 로컬 모드(단일 워커 전제)")
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            await self._redis.ping()
        except Exception:
            logger.warning("ws: Redis 연결 실패 → 로컬 모드로 폴백", exc_info=True)
            self._redis = None
            return
        self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("ws: Redis pub/sub 시작 (channel=%s)", _CHANNEL)

    async def _reader_loop(self) -> None:
        """구독이 끊기면 **다시 붙는다.**

        예전에는 한 번 끊기면 로그만 남기고 루프가 끝났다. `self._redis` 는 살아
        있어서 발행은 계속 되는데 이 워커는 아무것도 못 받는다 — 앱은 정상 연결로
        보이는데 남의 메시지만 안 오는, 재현이 어려운 장애가 된다.
        """
        backoff = _RESUBSCRIBE_MIN_S
        while True:
            try:
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(_CHANNEL)
                backoff = _RESUBSCRIBE_MIN_S  # 붙었으니 처음부터
                await self._read_forever()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("ws: Redis 구독 끊김 → %d초 뒤 재구독", backoff, exc_info=True)
            finally:
                pubsub, self._pubsub = self._pubsub, None
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RESUBSCRIBE_MAX_S)

    async def _read_forever(self) -> None:
        """구독 채널에서 브로드캐스트를 받아 이 워커의 로컬 소켓에 배달."""
        assert self._pubsub is not None
        async for msg in self._pubsub.listen():
            if msg.get("type") != "message":  # subscribe 확인 메시지 등 무시
                continue
            try:
                data = json.loads(msg["data"])
                if data.get("kick"):
                    await self._local_kick(data["employeeIds"])
                else:
                    await self._local_send(data["employeeIds"], data["payload"])
            except Exception:
                logger.warning("ws: 브로드캐스트 처리 실패", exc_info=True)

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except Exception:
                pass
            self._reader_task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except Exception:
                pass
            self._pubsub = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None


manager = ConnectionManager()
