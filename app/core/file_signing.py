"""업로드 파일 서명 URL — 비공개 파일(서명 PNG·문서·아바타) 보호 (CLAUDE.md §9.2, §H2).

정적 서빙(/uploads) 대신 서명된 링크로만 접근:
  DB의 '/uploads/2026/07/x.png' → 응답 직렬화 시 '/files/2026/07/x.png?exp=..&sig=..' 로 변환.
서명(HMAC)이 곧 인증이라 <img src> 처럼 헤더를 못 붙이는 로딩도 동작한다.
만료(기본 7일) 지나면 403 → 프론트가 목록/프로필을 재조회하면 새 서명 URL을 받는다.
"""

import hashlib
import hmac
from datetime import datetime, timezone

from app.core.config import settings

FILE_TTL_SECONDS = 7 * 24 * 3600  # 서명 URL 유효기간 — 7일


def _signature(rel_path: str, exp: int) -> str:
    msg = f"{rel_path}:{exp}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def sign_upload_url(url: str | None) -> str | None:
    """'/uploads/<rel>' → '/files/<rel>?exp=..&sig=..'. 그 외(None·http·이미 서명됨)는 그대로."""
    if not url or not url.startswith("/uploads/"):
        return url
    rel = url[len("/uploads/"):]
    exp = int(datetime.now(timezone.utc).timestamp()) + FILE_TTL_SECONDS
    return f"/files/{rel}?exp={exp}&sig={_signature(rel, exp)}"


def verify_file_signature(rel_path: str, exp: int, sig: str) -> bool:
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return False
    return hmac.compare_digest(_signature(rel_path, exp), sig)
