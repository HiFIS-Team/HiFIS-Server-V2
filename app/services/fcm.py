"""FCM 발송 — 안드로이드 앱 푸시.

[apns][app.services.apns] 와 **짝이다.** 애플은 애플 서버에 직접 치고,
안드로이드는 구글을 거친다. 기기 토큰을 받아 한 대씩 보내는 모양은 같다.

## 왜 안드로이드만 FCM 인가

구글이 다른 길을 안 준다. 애플은 `.p8` 키 하나로 `api.push.apple.com` 을
직접 칠 수 있는데, 안드로이드는 **FCM 을 반드시 거쳐야** 기기에 닿는다.
그래서 iOS·macOS 는 APNs 직접, 안드로이드만 FCM 이다
(FCM 으로 애플까지 보낼 수도 있지만 그러면 애플 쪽에 Firebase 가 하나 더
얹히므로 안 그러기로 했다 — 2026-08-06 결정).

## 열쇠가 APNs 와 다르다

| | APNs | FCM |
|---|---|---|
| 열쇠 | `.p8` 한 장 (팀 전체) | **서비스 계정 JSON** (프로젝트마다) |
| 서명 | ES256 | **RS256** |
| 인증 | JWT 를 그대로 헤더에 | JWT 로 **액세스 토큰을 받아서** 그걸로 |

한 단계가 더 있다 — JWT 를 구글에 주고 액세스 토큰(1시간)을 받아서, 그것으로
메시지를 보낸다. 토큰은 만료 전까지 재사용한다.

**새 의존성은 없다.** 서명은 `python-jose[cryptography]`(APNs 와 같은 것),
요청은 `httpx` 다.

설정(`fcm_*`)이 비면 조용히 넘어간다 — 앱 내 알림은 그대로 쌓인다.
"""

import json
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

#: 구글이 주는 액세스 토큰은 1시간짜리다. 만료 직전에 갈지 않게 45분에 새로 받는다
_TOKEN_TTL = 45 * 60

#: 이 응답이면 기기 토큰을 지운다 — 앱을 지웠거나 토큰이 갈렸다.
#: 안 지우면 죽은 토큰으로 계속 보내게 된다 (APNs 의 `_DEAD` 와 같은 뜻).
_DEAD = {"UNREGISTERED", "INVALID_ARGUMENT", "SENDER_ID_MISMATCH"}

_token_cache: tuple[str, float] | None = None
_client: httpx.AsyncClient | None = None


def _account() -> dict | None:
    """서비스 계정 JSON — `.env` 에 **한 줄로** 넣은 것을 푼다.

    APNs 개인키와 같은 사정이다 (`env_file` 이 여러 줄 값을 못 받는다).
    모양이 깨져 있으면 None 을 돌려주고 발송을 통째로 건너뛴다 — 여기서
    예외를 내면 알림 하나 때문에 요청 전체가 죽는다.
    """
    raw = settings.fcm_service_account
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("fcm 서비스 계정 JSON 을 못 읽었다: %s", exc)
        return None
    if not data.get("client_email") or not data.get("private_key"):
        logger.warning("fcm 서비스 계정에 client_email·private_key 가 없다")
        return None
    return data


def enabled() -> bool:
    return bool(settings.fcm_project_id and _account())


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def close() -> None:
    """앱 종료 훅에서 부른다 (안 불러도 프로세스가 끝나면 정리된다)"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _access_token() -> str | None:
    """구글 액세스 토큰 — 만료 전까지 **재사용한다**"""
    global _token_cache
    now = time.time()
    if _token_cache and now - _token_cache[1] < _TOKEN_TTL:
        return _token_cache[0]

    account = _account()
    if account is None:
        return None

    from jose import jwt  # python-jose[cryptography] — APNs·로그인 토큰과 같은 것

    assertion = jwt.encode(
        {
            "iss": account["client_email"],
            "scope": _SCOPE,
            "aud": _TOKEN_URL,
            "iat": int(now),
            "exp": int(now) + 3600,
        },
        account["private_key"],
        algorithm="RS256",
    )
    try:
        response = await _http().post(
            _TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        response.raise_for_status()
        token = response.json()["access_token"]
    except Exception as exc:
        logger.warning("fcm 액세스 토큰 실패: %s", exc)
        return None

    _token_cache = (token, now)
    return token


async def send(
    *,
    token: str,
    title: str,
    body: str | None,
    link: str | None,
    type: str,
) -> str | None:
    """기기 하나에 보낸다 — 성공하면 None, **토큰이 죽었으면 그 이유**를 돌려준다.

    `notification` 과 `data` 를 **둘 다** 싣는다. 앞엣것은 안드로이드가 알아서
    띄우는 배너이고, 뒤엣것은 눌렀을 때 어디로 갈지다 (`link`). 데이터만 보내면
    앱이 꺼져 있을 때 아무것도 안 뜬다.

    **`data` 의 값은 전부 문자열이어야 한다** — FCM 이 그렇게 못 박아 뒀다.
    """
    access = await _access_token()
    if access is None:
        return None

    message = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body or ""},
            "data": {"type": type, **({"link": link} if link else {})},
            "android": {
                "priority": "HIGH",
                # 눌렀을 때 앱을 여는 자리 — 안드로이드 기본 동작이라 따로 안 준다
                "notification": {"sound": "default"},
            },
        }
    }
    url = f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send"
    try:
        response = await _http().post(
            url,
            content=json.dumps(message, ensure_ascii=False).encode(),
            headers={
                "authorization": f"Bearer {access}",
                "content-type": "application/json; charset=utf-8",
            },
        )
    except Exception as exc:  # 네트워크 등 — 앱 내 알림은 유지된다
        logger.warning("fcm 예외: %s", exc)
        return None

    if response.status_code == 200:
        return None

    reason = ""
    try:
        error = response.json().get("error", {})
        # 자세한 이유는 details 안에 있다 (`errorCode`). 없으면 status 를 쓴다
        for detail in error.get("details", []):
            if detail.get("errorCode"):
                reason = detail["errorCode"]
                break
        reason = reason or error.get("status", "")
    except Exception:
        reason = response.text[:120]

    if response.status_code == 404 or reason in _DEAD:
        return reason or "UNREGISTERED"
    logger.warning("fcm 실패(%s): %s", response.status_code, reason)
    return None
