"""APNs 발송 — 앱(iOS·macOS) 푸시.

웹푸시(`pywebpush`)와 **길이 다르다.** 저쪽은 브라우저가 준 endpoint 로 보내고,
이건 애플 서버(`api.push.apple.com`)에 **기기 토큰**으로 보낸다.

FCM 을 안 끼운 이유 — 애플에 보내려면 어차피 `.p8` 키가 필요한데, FCM 을 쓰면
거기에 Firebase 프로젝트와 SDK 가 하나 더 얹힌다. iOS·macOS 만 보면 직접 치는
쪽이 짧다 (2026-08-06 결정). 안드로이드를 붙일 때 FCM 을 따로 얹으면 된다.

**HTTP/2 가 필수다** — 애플이 HTTP/1.1 을 안 받는다. `httpx[http2]`(h2) 가 있어야 한다.
설정(`apns_*`)이 비면 조용히 넘어간다 — 앱 내 알림은 그대로 쌓인다.
"""

import json
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_PROD_HOST = "https://api.push.apple.com"
_SANDBOX_HOST = "https://api.sandbox.push.apple.com"

#: 애플 권장 — 인증 토큰을 20분보다 자주 새로 만들면 **429 TooManyProviderTokenUpdates** 다.
#: 유효기간은 1시간이라 그 사이 값으로 잡는다.
_JWT_TTL = 45 * 60

#: 지운 토큰으로 계속 보내지 말라는 뜻 — 이 응답이면 기기 토큰을 지운다
_DEAD = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic", "TopicDisallowed"}

_jwt_cache: tuple[str, float] | None = None
_client: httpx.AsyncClient | None = None


def enabled() -> bool:
    return bool(settings.apns_key_id and settings.apns_team_id and settings.apns_private_key)


def _auth_token() -> str:
    """provider 인증 토큰 (ES256) — 만료 전까지 **재사용한다**"""
    global _jwt_cache
    now = time.time()
    if _jwt_cache and now - _jwt_cache[1] < _JWT_TTL:
        return _jwt_cache[0]
    from jose import jwt  # python-jose[cryptography] — 이미 로그인 토큰에 쓰고 있다

    token = jwt.encode(
        {"iss": settings.apns_team_id, "iat": int(now)},
        settings.apns_private_key,
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )
    _jwt_cache = (token, now)
    return token


def _http() -> httpx.AsyncClient:
    """연결을 계속 쓴다 — 요청마다 새로 맺으면 TLS 악수가 매번 붙는다"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(http2=True, timeout=10.0)
    return _client


async def close() -> None:
    """앱 종료 훅에서 부른다 (안 불러도 프로세스가 끝나면 정리된다)"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def send(
    *,
    token: str,
    sandbox: bool,
    title: str,
    body: str | None,
    link: str | None,
    type: str,
    badge: int | None = None,
) -> str | None:
    """기기 하나에 보낸다 — 성공하면 None, **토큰이 죽었으면 그 이유**를 돌려준다.

    돌려준 이유가 있으면 부르는 쪽이 그 토큰을 지운다. 안 지우면 죽은 토큰으로
    계속 보내다가 애플이 막는다.
    """
    payload = {
        "aps": {
            "alert": {"title": title, "body": body or ""},
            "sound": "default",
            # 알림함 배지 — 값을 안 주면 그대로 둔다
            **({"badge": badge} if badge is not None else {}),
        },
        # 앱이 알림을 눌렀을 때 어디로 갈지 — 알림함의 `link` 와 같은 값이다
        "link": link,
        "type": type,
    }
    host = _SANDBOX_HOST if sandbox else _PROD_HOST
    try:
        response = await _http().post(
            f"{host}/3/device/{token}",
            content=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "authorization": f"bearer {_auth_token()}",
                "apns-topic": settings.apns_topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
        )
    except Exception as exc:  # 네트워크 등 — 앱 내 알림은 유지된다
        logger.warning("apns 예외: %s", exc)
        return None

    if response.status_code == 200:
        return None
    reason = ""
    try:
        reason = response.json().get("reason", "")
    except Exception:
        reason = response.text[:120]
    # 410 은 기기에서 앱을 지운 것 — 토큰을 지운다
    if response.status_code == 410 or reason in _DEAD:
        return reason or "Unregistered"
    logger.warning("apns 실패(%s): %s", response.status_code, reason)
    return None
