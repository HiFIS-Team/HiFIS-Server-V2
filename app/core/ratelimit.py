"""레이트리밋 — slowapi (CLAUDE.md §9.7). 로그인·웹훅 무차별 대입/스팸 방지.

기본은 인메모리 저장(홈서버 단일 박스엔 충분). 다중 워커/프로세스로 확장 시
Limiter(storage_uri=settings.redis_url) 로 Redis 공유 권장.
프록시(Caddy/Cloudflare) 뒤에선 X-Forwarded-For 첫 홉을 클라이언트 키로 사용.
swallow_errors=True → 저장소 오류 시 fail-open(레이트리밋이 인증을 마비시키지 않게).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# 카운터를 Redis 에 공유 → 워커가 몇 개든 한도를 합산(멀티워커 정확 제한).
# Redis 장애 시 swallow_errors=True 로 fail-open(레이트리밋이 로그인을 마비시키지 않게).
limiter = Limiter(
    key_func=client_key,
    storage_uri=settings.redis_url,
    swallow_errors=True,
)
