"""서명 URL 파일 서빙 — 비공개 업로드(서명·문서·아바타) (CLAUDE.md §9.2, §H2).

인증 헤더 대신 쿼리의 exp/sig(HMAC) 로만 접근 허용 → <img src> 로딩 가능.
경로 탈출(..) 은 realpath 로 uploads/ 하위인지 검증해 차단.
"""

import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.file_signing import verify_file_signature

router = APIRouter(tags=["files"])

_UPLOAD_ROOT = os.path.realpath("uploads")


@router.get("/files/{file_path:path}")
async def serve_signed_file(
    file_path: str,
    exp: int = Query(...),
    sig: str = Query(...),
) -> FileResponse:
    if not verify_file_signature(file_path, exp, sig):
        raise HTTPException(403, detail={"code": "INVALID_FILE_SIGNATURE", "message": "만료되었거나 유효하지 않은 파일 링크입니다"})
    full = os.path.realpath(os.path.join(_UPLOAD_ROOT, file_path))
    if full != _UPLOAD_ROOT and not full.startswith(_UPLOAD_ROOT + os.sep):  # 경로 탈출 차단
        raise HTTPException(400, detail={"code": "INVALID_PATH", "message": "잘못된 경로입니다"})
    if not os.path.isfile(full):
        raise HTTPException(404, detail={"code": "FILE_MISSING", "message": "파일이 존재하지 않습니다"})
    return FileResponse(
        full,
        headers={"Cache-Control": "private, max-age=604800"},
    )
