"""IP → 지역 한 줄. SSH 접속 알림에 "어디서 들어왔나"를 붙이는 데 쓴다.

무료 조회 서비스(`ip-api.com`)에 물어본다. GeoIP DB 를 서버에 얹는 방법도 있지만
파일이 수십 MB 에 갱신 관리가 붙는다 — SSH 접속은 하루 몇 번이라 그럴 값어치가 없다.

**실패해도 조용히 넘어간다.** 지역은 곁가지지 알림의 본문이 아니다.
조회가 안 되면 그 줄만 빠지고 알림은 그대로 간다.
"""

import ipaddress

import httpx

_TIMEOUT = 3.0
# **한국어(`lang=ko`)는 무료 엔드포인트에서 무시된다** — 넣어도 영어로 온다.
# 알림에서 하는 일은 "아는 곳인가"를 가리는 것이라 영어여도 충분하다.
_URL = "http://ip-api.com/json/{ip}?fields=status,country,city"


def _private(ip: str) -> bool:
    """사설·루프백 주소인가 — 밖에 물어봐야 답이 없다."""
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


async def region_of(ip: str) -> str | None:
    """'대한민국 광주' 처럼 한 줄. 모르면 None.

    사설 IP 는 **조회하지 않고** '내부망' 이라고 답한다 (같은 공유기 안이다).
    """
    if not ip or ip == "local":
        return "서버 자신"
    if _private(ip):
        return "내부망"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            data = (await client.get(_URL.format(ip=ip))).json()
        if data.get("status") != "success":
            return None
        parts = [data.get("country"), data.get("city")]
        return " ".join(p for p in parts if p) or None
    except Exception:
        return None  # 조회 실패는 알림을 막지 않는다
