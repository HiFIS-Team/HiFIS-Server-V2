"""로컬 디스크 파일 저장 — 서명 이미지 등 (CLAUDE.md §9.2).

저장 경로: uploads/{yyyy}/{mm}/{uuid}.{ext}. 홈서버 로컬 디스크(클라우드 X).
"""

import base64
import binascii
import os
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile

UPLOAD_ROOT = "uploads"
_CHUNK = 1024 * 1024  # 1MB
_AVATAR_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_AVATAR_MAX = 5 * 1024 * 1024  # 5MB


async def _save_image(upload: UploadFile, folder: str) -> str:
    """이미지를 uploads/{folder}/ 에 저장하고 서빙 경로 반환(확장자·용량 검증).

    아바타와 환경정비 사진이 같이 쓴다 — 검증 기준이 갈리면 한쪽만 큰 파일을
    받아 디스크가 찬다.
    """
    filename = upload.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _AVATAR_EXTS:
        raise HTTPException(400, detail={"code": "INVALID_IMAGE", "message": "이미지 파일만 업로드할 수 있습니다(png/jpg/gif/webp)"})
    now = datetime.now(timezone.utc)
    rel_dir = f"{UPLOAD_ROOT}/{folder}/{now:%Y}/{now:%m}"
    os.makedirs(rel_dir, exist_ok=True)
    rel_path = f"{rel_dir}/{uuid.uuid4().hex}.{ext}"
    size = 0
    with open(rel_path, "wb") as out:
        while chunk := await upload.read(_CHUNK):
            size += len(chunk)
            if size > _AVATAR_MAX:
                out.close()
                os.remove(rel_path)
                raise HTTPException(400, detail={"code": "IMAGE_TOO_LARGE", "message": "이미지는 5MB 이하만 가능합니다"})
            out.write(chunk)
    return f"/{rel_path}"


async def save_avatar(upload: UploadFile) -> str:
    """아바타 이미지를 uploads/avatars/ 에 저장하고 서빙 경로 반환."""
    return await _save_image(upload, "avatars")


async def save_env_photo(upload: UploadFile) -> str:
    """환경정비 수행 사진을 uploads/env/ 에 저장하고 서빙 경로 반환.

    현수막처럼 **한 것을 눈으로 확인해야 하는 항목**이 쓴다 (2026-08-18).
    """
    return await _save_image(upload, "env")


async def save_upload(upload: UploadFile) -> tuple[str, str, int]:
    """멀티파트 파일을 청크 스트리밍으로 디스크에 저장. (serving url, ext, size_bytes) 반환."""
    filename = upload.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    now = datetime.now(timezone.utc)
    rel_dir = f"{UPLOAD_ROOT}/documents/{now:%Y}/{now:%m}"
    os.makedirs(rel_dir, exist_ok=True)
    rel_path = f"{rel_dir}/{uuid.uuid4().hex}.{ext}"
    size = 0
    with open(rel_path, "wb") as out:
        while chunk := await upload.read(_CHUNK):
            size += len(chunk)
            out.write(chunk)
    return f"/{rel_path}", ext, size


def save_signature(signature_base64: str) -> str:
    """base64(PNG) 서명을 디스크에 저장하고 서빙 경로(/uploads/...)를 반환."""
    data = signature_base64.strip()
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]  # data URL 접두 제거
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, detail={"code": "INVALID_SIGNATURE", "message": "서명 이미지 디코딩에 실패했습니다"})
    if not raw:
        raise HTTPException(400, detail={"code": "INVALID_SIGNATURE", "message": "빈 서명 이미지입니다"})

    now = datetime.now(timezone.utc)
    rel_dir = f"{UPLOAD_ROOT}/{now:%Y}/{now:%m}"
    os.makedirs(rel_dir, exist_ok=True)
    rel_path = f"{rel_dir}/{uuid.uuid4().hex}.png"
    with open(rel_path, "wb") as f:
        f.write(raw)
    return f"/{rel_path}"
