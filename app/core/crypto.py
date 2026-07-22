"""계정 비밀번호 암호화 — AES-256-GCM (CLAUDE.md §9.6).

마스터 키는 .env(ACCOUNT_MASTER_KEY, 파일 권한 600)에서 로드. 클라우드 KMS 없음(홈서버).
GCM 인증 태그는 ciphertext 뒤 16바이트에 포함되므로 nonce + ciphertext 만 저장한다.
"""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def _key() -> bytes:
    key = bytes.fromhex(settings.account_master_key)
    if len(key) != 32:
        raise RuntimeError("ACCOUNT_MASTER_KEY 는 64 hex(32 byte) 여야 합니다")
    return key


def encrypt_secret(plaintext: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce, ciphertext


def decrypt_secret(nonce: bytes, ciphertext: bytes) -> str:
    return AESGCM(_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
