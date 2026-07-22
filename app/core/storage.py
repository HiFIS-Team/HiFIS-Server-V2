"""로컬 디스크 파일 저장 — 서명 이미지 등 (CLAUDE.md §9.2).

저장 경로: uploads/{yyyy}/{mm}/{uuid}.{ext}. 홈서버 로컬 디스크(클라우드 X).
"""

import base64
import binascii
import os
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

UPLOAD_ROOT = "uploads"


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
