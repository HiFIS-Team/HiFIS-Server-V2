"""업로드 파일 서명 URL — 비공개 파일(서명 PNG·문서·아바타) 보호 (CLAUDE.md §9.2, §H2).

정적 서빙(/uploads) 대신 서명된 링크로만 접근:
  DB의 '/uploads/2026/07/x.png' → 응답 직렬화 시 '/files/2026/07/x.png?exp=..&sig=..' 로 변환.
서명(HMAC)이 곧 인증이라 <img src> 처럼 헤더를 못 붙이는 로딩도 동작한다.
만료(기본 7일) 지나면 403 → 프론트가 목록/프로필을 재조회하면 새 서명 URL을 받는다.
"""

import hashlib
import hmac
from datetime import datetime, timezone
from functools import lru_cache

from app.core.config import settings

FILE_TTL_SECONDS = 7 * 24 * 3600  # 서명 URL 유효기간 — 7일


@lru_cache(maxsize=1)
def _key() -> bytes:
    """파일 서명 전용 키.

    예전엔 `jwt_secret` 을 그대로 HMAC 키로 썼다. 용도가 다른 두 서명이 같은 키를
    쓰면 한쪽만 유출돼도 다른 쪽까지 위조된다(그리고 JWT 시크릿을 돌리는 순간
    멀쩡한 파일 링크가 전부 죽는다). `FILE_SIGNING_KEY` 를 주면 그걸 쓰고,
    없으면 JWT 시크릿에서 **되돌릴 수 없게** 파생한 별도 키를 만든다.
    """
    if settings.file_signing_key:
        return settings.file_signing_key.encode("utf-8")
    return hashlib.sha256(b"hifis.file-signing.v1|" + settings.jwt_secret.encode("utf-8")).digest()


def _signature(rel_path: str, exp: int) -> str:
    msg = f"{rel_path}:{exp}".encode("utf-8")
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:32]


def _legacy_signature(rel_path: str, exp: int) -> str:
    """키를 나누기 전(= `jwt_secret` 직접 사용) 방식.

    **검증에서만 쓴다.** 이 코드가 올라가는 순간 이미 나가 있는 링크가 전부
    서명이 달라지는데, 그건 지금 열려 있는 화면의 사진·서명 이미지가 한꺼번에
    깨진다는 뜻이다. 링크 수명이 7일이라 그때까진 옛 서명도 받아 준다.
    **배포 후 7일 지나면 이 함수와 호출부를 지운다.**
    """
    msg = f"{rel_path}:{exp}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def sign_upload_url(url: str | None) -> str | None:
    """'/uploads/<rel>' → '/files/<rel>?exp=..&sig=..'. 그 외(None·http·이미 서명됨)는 그대로."""
    if not url or not url.startswith("/uploads/"):
        return url
    rel = url[len("/uploads/"):]
    exp = int(datetime.now(timezone.utc).timestamp()) + FILE_TTL_SECONDS
    return f"/files/{rel}?exp={exp}&sig={_signature(rel, exp)}"


def unsign_upload_url(url: str | None) -> str | None:
    """'/files/<rel>?exp=..&sig=..' → '/uploads/<rel>'. 그 외는 그대로.

    **받아 적는 쪽에서 쓴다.** 앱은 목록에서 받은 그대로를 다시 돌려보내는데,
    그건 이미 서명이 붙은 주소다. 그대로 저장하면 DB에 서명이 박히고 — 7일 뒤
    만료되는 데다 다음 조회에서 한 번 더 서명돼 아예 못 여는 주소가 된다.
    """
    if not url or not url.startswith("/files/"):
        return url
    rel = url[len("/files/"):].split("?", 1)[0]
    return f"/uploads/{rel}"


def verify_file_signature(rel_path: str, exp: int, sig: str) -> bool:
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return False
    if hmac.compare_digest(_signature(rel_path, exp), sig):
        return True
    return hmac.compare_digest(_legacy_signature(rel_path, exp), sig)
