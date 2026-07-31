"""공유 async Redis 클라이언트 (CLAUDE.md §8).

레이트리밋(slowapi)·WS 팬아웃·스케줄러 락은 각자 클라이언트를 쓰지만,
앱 로직(비번 재설정 코드 등)에서 쓸 범용 클라이언트를 여기서 지연 초기화해 재사용한다.
from_url 은 즉시 연결하지 않고 커넥션 풀만 만든다 → 첫 명령에서 연결.
"""

import redis.asyncio as aioredis

from app.core.config import settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _client
