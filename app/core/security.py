"""비밀번호 해시(bcrypt) + JWT 발급/검증 (CLAUDE.md §8, §9.1).

passlib 은 bcrypt 5.x 와 비호환이라 bcrypt 를 직접 사용한다.
bcrypt 72바이트 한계는 sha256 프리해시(base64)로 회피.
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import HTTPException
from jose import JWTError, jwt

from app.core.config import settings


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str) -> str:
    return _create_token(subject, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(subject: str) -> str:
    return _create_token(subject, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "유효하지 않은 토큰입니다"})
    if payload.get("type") != expected_type:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "토큰 유형이 올바르지 않습니다"})
    return payload
