"""문서함 라우터 — Folder/Document + 멀티파트 업로드·다운로드 (CLAUDE.md §6.6, §9.2)."""

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.storage import save_upload
from app.db.session import get_db
from app.enums import Role
from app.models.document import Document, Folder
from app.models.employee import Employee
from app.schemas.document import DocumentOut, DocumentUpdate, FolderCreate, FolderOut, FolderUpdate

router = APIRouter(tags=["documents"], dependencies=[Depends(get_current_user)])


def _parse_tags(raw: str | None) -> list[str]:
    return [t.strip() for t in raw.split(",")] if raw and raw.strip() else []


# ---------- Folder ----------
@router.get("/folders", response_model=list[FolderOut])
async def list_folders(
    db: AsyncSession = Depends(get_db),
    space: str | None = Query(None),
    scope: str | None = Query(None),
) -> list[Folder]:
    stmt = select(Folder)
    if space:
        stmt = stmt.where(Folder.space == space)
    if scope:
        stmt = stmt.where(Folder.scope == scope)
    result = await db.execute(stmt.order_by(Folder.name))
    return list(result.scalars().all())


@router.post("/folders", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Folder:
    folder = Folder(
        name=payload.name,
        scope=payload.scope,
        space=payload.space,
        parent_id=payload.parent_id,
        created_by_id=current.id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: str, payload: FolderUpdate, db: AsyncSession = Depends(get_db)
) -> Folder:
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, detail={"code": "FOLDER_NOT_FOUND", "message": "폴더를 찾을 수 없습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(folder, key, value)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)) -> None:
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, detail={"code": "FOLDER_NOT_FOUND", "message": "폴더를 찾을 수 없습니다"})
    await db.execute(delete(Document).where(Document.folder_id == folder_id))  # 하위 문서 함께
    await db.delete(folder)
    await db.commit()
    return None


# ---------- Document ----------
@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    space: str | None = Query(None),
    scope: str | None = Query(None),
    folder_id: str | None = Query(None, alias="folderId"),
    q: str | None = Query(None),
) -> list[Document]:
    stmt = select(Document)
    if space:
        stmt = stmt.where(Document.space == space)
    if scope:
        stmt = stmt.where(Document.scope == scope)
    if folder_id:
        stmt = stmt.where(Document.folder_id == folder_id)
    if q:
        stmt = stmt.where(or_(Document.name.ilike(f"%{q}%"), Document.desc.ilike(f"%{q}%")))
    result = await db.execute(stmt.order_by(Document.created_at.desc()))
    return list(result.scalars().all())


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    scope: str = Form(...),
    space: str = Form(...),
    folder_id: str | None = Form(None, alias="folderId"),
    name: str | None = Form(None),
    desc: str | None = Form(None),
    tags: str | None = Form(None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    if folder_id and await db.get(Folder, folder_id) is None:
        raise HTTPException(400, detail={"code": "FOLDER_NOT_FOUND", "message": "폴더가 존재하지 않습니다"})
    url, ext, size = await save_upload(file)
    document = Document(
        name=name or (file.filename or "file"),
        ext=ext,
        size_bytes=size,
        url=url,
        scope=scope,
        space=space,
        folder_id=folder_id,
        tags=_parse_tags(tags),
        desc=desc,
        uploader_id=current.id,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: str, payload: DocumentUpdate, db: AsyncSession = Depends(get_db)
) -> Document:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return document


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    if current.role != Role.ADMIN and document.uploader_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "업로더 또는 관리자만 삭제할 수 있습니다"})
    path = document.url.lstrip("/")
    if os.path.exists(path):
        os.remove(path)
    await db.delete(document)
    await db.commit()
    return None


@router.get("/documents/{document_id}/download")
async def download_document(document_id: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    path = document.url.lstrip("/")
    if not os.path.exists(path):
        raise HTTPException(404, detail={"code": "FILE_MISSING", "message": "파일이 존재하지 않습니다"})
    download_name = document.name if document.name.endswith(f".{document.ext}") else f"{document.name}.{document.ext}"
    return FileResponse(path, filename=download_name)
