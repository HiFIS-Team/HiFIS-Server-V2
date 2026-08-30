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
_CHAT_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
_CHAT_MAX = 5 * 1024 * 1024  # 5MB

#: 운동일지 자료 — 자세 확인용이라 영상을 받는다
_WORKOUT_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_WORKOUT_VIDEO_EXTS = {"mp4", "mov", "m4v", "webm"}
_WORKOUT_IMAGE_MAX = 10 * 1024 * 1024  # 10MB
#: 영상 상한 — 홈서버 디스크 한 대가 전부라 무제한은 곧 장애다.
#: 한 세트 찍은 영상이 30초 안팂이라 이면 넘친다.
_WORKOUT_VIDEO_MAX = 100 * 1024 * 1024  # 100MB

#: 일반 첨부 상한 — 홈서버 디스크 한 대가 전부라 무제한은 곧 장애다
_DOC_MAX = 50 * 1024 * 1024  # 50MB
#: 브라우저에서 **실행되는** 형식 — 화이트리스트를 못 쓰는 자리(계약서·엑셀·한글 등
#: 무엇이 올라올지 모른다)라 위험한 것만 잘라 낸다
_BLOCKED_EXTS = {
    "html", "htm", "xhtml", "shtml", "svg", "js", "mjs", "xml", "swf",
    "exe", "dll", "bat", "cmd", "com", "scr", "msi", "sh", "ps1", "jar",
}
#: 브라우저에 그대로 띄워도 되는 형식 — 나머지는 전부 내려받기로 강제한다
#:
#: 영상은 **반드시 여기에 있어야 한다.** 앜이 재생기를 못 담아서(플레이어가
#: 윈도우를 안 탄다) 운동일지 영상은 기기 브라우저로 넘긴다 — 내려받기로
#: 강제되면 재생이 안 되고 파일만 떨어진다.
INLINE_EXTS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "pdf",
    "mp4",
    "mov",
    "m4v",
    "webm",
}


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
    """멀티파트 파일을 청크 스트리밍으로 디스크에 저장. (serving url, ext, size_bytes) 반환.

    예전엔 확장자도 용량도 안 봤다. 홈서버 한 대라 **누가 큰 파일 하나만 올려도
    디스크가 차서 DB까지 같이 죽는다.** 실행되는 확장자(html/svg/js…)도 막는다 —
    파일은 API와 같은 오리진에서 서빙되므로 세션 토큰이 노출될 수 있다.
    """
    filename = upload.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    if not ext.isalnum() or len(ext) > 10:  # 경로 조작·이상한 확장자 차단
        ext = "bin"
    if ext in _BLOCKED_EXTS:
        raise HTTPException(
            400,
            detail={"code": "INVALID_FILE_TYPE", "message": "업로드할 수 없는 형식의 파일입니다"},
        )
    now = datetime.now(timezone.utc)
    rel_dir = f"{UPLOAD_ROOT}/documents/{now:%Y}/{now:%m}"
    os.makedirs(rel_dir, exist_ok=True)
    rel_path = f"{rel_dir}/{uuid.uuid4().hex}.{ext}"
    size = 0
    try:
        with open(rel_path, "wb") as out:
            while chunk := await upload.read(_CHUNK):
                size += len(chunk)
                if size > _DOC_MAX:
                    raise HTTPException(
                        400,
                        detail={"code": "FILE_TOO_LARGE", "message": "파일은 50MB 이하만 업로드할 수 있습니다"},
                    )
                out.write(chunk)
    except Exception:
        # 중간에 끊긴 조각을 남기지 않는다 — 참조 없는 파일은 아무도 못 지운다
        if os.path.exists(rel_path):
            os.remove(rel_path)
        raise
    return f"/{rel_path}", ext, size


async def save_chat_upload(upload: UploadFile) -> tuple[str, str, int]:
    """사내톡 이미지 업로드를 검증하고 저장한다."""
    filename = upload.filename or "file.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _CHAT_EXTS:
        raise HTTPException(400, detail={"code": "INVALID_IMAGE", "message": "사내톡에는 이미지 파일만 첨부할 수 있습니다"})

    now = datetime.now(timezone.utc)
    rel_dir = f"{UPLOAD_ROOT}/chat/{now:%Y}/{now:%m}"
    os.makedirs(rel_dir, exist_ok=True)
    rel_path = f"{rel_dir}/{uuid.uuid4().hex}.{ext}"
    size = 0
    try:
        with open(rel_path, "wb") as out:
            while chunk := await upload.read(_CHUNK):
                size += len(chunk)
                if size > _CHAT_MAX:
                    raise HTTPException(400, detail={"code": "IMAGE_TOO_LARGE", "message": "사내톡 이미지는 5MB 이하만 가능합니다"})
                out.write(chunk)
    except Exception:
        if os.path.exists(rel_path):
            os.remove(rel_path)
        raise
    return f"/{rel_path}", ext, size


async def save_workout_media(upload: UploadFile) -> tuple[str, str]:
    """운동일지 자료(사진·영상)를 uploads/workout/ 에 저장. (serving url, "IMAGE"|"VIDEO") 반환.

    사진과 영상의 상한이 다르다 — 영상은 원래 크고, 사진은 클 이유가 없다.
    """
    filename = upload.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _WORKOUT_IMAGE_EXTS:
        kind, limit, limit_text = "IMAGE", _WORKOUT_IMAGE_MAX, "사진은 10MB"
    elif ext in _WORKOUT_VIDEO_EXTS:
        kind, limit, limit_text = "VIDEO", _WORKOUT_VIDEO_MAX, "영상은 100MB"
    else:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_MEDIA",
                "message": "사진(png/jpg/gif/webp) 또는 영상(mp4/mov/webm)만 올릴 수 있습니다",
            },
        )

    now = datetime.now(timezone.utc)
    rel_dir = f"{UPLOAD_ROOT}/workout/{now:%Y}/{now:%m}"
    os.makedirs(rel_dir, exist_ok=True)
    rel_path = f"{rel_dir}/{uuid.uuid4().hex}.{ext}"
    size = 0
    try:
        with open(rel_path, "wb") as out:
            while chunk := await upload.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        400,
                        detail={
                            "code": "MEDIA_TOO_LARGE",
                            "message": f"{limit_text} 이하만 올릴 수 있습니다",
                        },
                    )
                out.write(chunk)
    except Exception:
        # 중간에 끊긴 조각을 남기지 않는다 — 참조 없는 파일은 아무도 못 지운다
        if os.path.exists(rel_path):
            os.remove(rel_path)
        raise
    return f"/{rel_path}", kind


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
